"""Les noeuds du graphe, regroupes sur un objet qui porte leurs dependances.

Separe du cablage (`graph.py`) pour que ce dernier se lise comme le schema :
qui parle a qui, dans quel ordre. Ici, ce que chaque noeud fait.

Un invariant traverse tout le fichier : **la decision de routage n'est jamais
stockee dans l'etat**, chaque noeud la recalcule avec `decide(...)`. C'est une
fonction pure et bon marche, et un etat qui porte une decision derivee finit
toujours par porter une decision perimee -- ici, juste apres une relance qui
vient precisement de changer les hypotheses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from council.agents.arbiter import Arbiter
from council.agents.base import BaseSpecialist
from council.llm.client import LLMClient
from council.models import (
    CallUsage,
    Clarification,
    ConsensusKind,
    Incident,
    SpecialistName,
    Verdict,
)
from council.orchestration.routing import RoutingDecision, decide, latest_by_agent
from council.orchestration.state import InvestigationState
from council.orchestration.trace import Tracer

NodeFn = Callable[[InvestigationState], dict[str, Any]]


def totals(usages: Sequence[CallUsage]) -> dict[str, Any]:
    return {
        "llm_calls": len(usages),
        "input_tokens": sum(u.input_tokens for u in usages),
        "output_tokens": sum(u.output_tokens for u in usages),
        "usd": sum(u.usd for u in usages),
        "latency_ms": sum(u.latency_ms for u in usages),
    }


@dataclass
class CouncilNodes:
    """Les dependances de l'investigation, passees une fois au lieu d'etre globales."""

    specialists: Sequence[BaseSpecialist]
    arbiter: Arbiter
    client: LLMClient
    tracer: Tracer
    effort_specialist: str = "low"
    max_rounds: int = 2
    _by_name: dict[SpecialistName, BaseSpecialist] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name = {s.name: s for s in self.specialists}

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _incident(state: InvestigationState) -> Incident:
        return state["incident"]

    def _decision(self, state: InvestigationState) -> RoutingDecision:
        return decide(state["hypotheses"], state.get("rounds", 0), self.max_rounds)

    # -- noeuds --------------------------------------------------------------

    def specialist(self, name: SpecialistName) -> NodeFn:
        """Une branche du fan-out. Les trois s'executent au meme super-pas."""

        def node(state: InvestigationState) -> dict[str, Any]:
            incident = self._incident(state)
            hypothesis, usage = self._by_name[name].analyse(
                incident, self.client, self.effort_specialist
            )
            self.tracer.emit(
                incident.id,
                f"specialist:{name.value}",
                "hypothesis",
                cause=None if hypothesis.cause is None else hypothesis.cause.value,
                confidence=hypothesis.confidence,
                evidence_count=len(hypothesis.evidence),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                from_cache=usage.from_cache,
            )
            return {"hypotheses": [hypothesis], "usages": [usage]}

        return node

    def route(self, state: InvestigationState) -> dict[str, Any]:
        incident = self._incident(state)
        rounds = state.get("rounds", 0)
        decision = self._decision(state)
        self.tracer.emit(
            incident.id,
            "route",
            "routing",
            route=decision.route.value,
            kind=decision.kind.value,
            leading_cause=(
                None if decision.leading_cause is None else decision.leading_cause.value
            ),
            support=decision.support,
            answered=decision.answered,
            abstained=decision.abstained,
            divergent=None if decision.divergent is None else decision.divergent.value,
            rounds_used=rounds,
            reason=decision.reason,
        )
        return {"route": decision.route.value}

    def clarify(self, state: InvestigationState) -> dict[str, Any]:
        """L'arbitre formule une question, l'agent divergent re-regarde SES donnees.

        Il ne recoit jamais les donnees des autres : on lui demande de justifier,
        pas de se rallier a une information qu'il n'a aucun moyen de verifier.
        """
        incident = self._incident(state)
        rounds = state.get("rounds", 0)
        decision = self._decision(state)
        assert decision.divergent is not None
        current = latest_by_agent(state["hypotheses"])
        round_index = rounds + 1

        question, question_usage = self.arbiter.formulate_question(
            incident.id, current, decision, self.client, round_index
        )
        before = current[decision.divergent]
        revised, answer_usage = self._by_name[decision.divergent].reask(
            incident, self.client, self.effort_specialist, question, round_index
        )
        clarification = Clarification(
            round_index=round_index,
            target=decision.divergent,
            question=question,
            answer_cause=revised.cause,
            answer_confidence=revised.confidence,
            changed_mind=revised.cause is not before.cause,
        )
        self.tracer.emit(
            incident.id,
            "clarify",
            "clarification",
            round_index=round_index,
            target=decision.divergent.value,
            question=question,
            answer_cause=None if revised.cause is None else revised.cause.value,
            changed_mind=clarification.changed_mind,
        )
        return {
            "hypotheses": [revised],
            "clarifications": [clarification],
            "usages": [question_usage, answer_usage],
            "rounds": round_index,
        }

    def conclude(self, state: InvestigationState) -> dict[str, Any]:
        incident = self._incident(state)
        rounds = state.get("rounds", 0)
        decision = self._decision(state)
        cause, confidence, rejected, reasoning, usage = self.arbiter.synthesize(
            incident.id, latest_by_agent(state["hypotheses"]), decision, self.client
        )
        usages = [*state.get("usages", []), usage]
        # Plafond structurel : la confiance auto-declaree n'est pas fiable tant
        # que la calibration n'a pas montre le contraire ; la forme de l'accord,
        # elle, est observee.
        capped = min(confidence, decision.ceiling)
        verdict = Verdict(
            incident_id=incident.id,
            cause=cause,
            confidence=capped,
            consensus=decision.kind,
            rejected=rejected,
            reasoning=reasoning,
            rounds=rounds,
            recommend_human_review=decision.kind
            in (ConsensusKind.SINGLE_SOURCE, ConsensusKind.MAJORITY),
            **totals(usages),
        )
        self.tracer.emit(
            incident.id,
            "conclude",
            "verdict",
            cause=cause.value,
            confidence=capped,
            declared_confidence=confidence,
            consensus=decision.kind.value,
            rounds=rounds,
            llm_calls=verdict.llm_calls,
            usd=verdict.usd,
        )
        return {"verdict": verdict, "usages": [usage]}

    def split(self, state: InvestigationState) -> dict[str, Any]:
        """Desaccord total : on ne tranche pas, on publie les pistes."""
        incident = self._incident(state)
        rounds = state.get("rounds", 0)
        decision = self._decision(state)
        tracks, next_step, reasoning, usage = self.arbiter.report_split(
            incident.id, latest_by_agent(state["hypotheses"]), decision, self.client
        )
        usages = [*state.get("usages", []), usage]
        verdict = Verdict(
            incident_id=incident.id,
            cause=None,
            confidence=0.0,
            consensus=decision.kind,
            tracks=tracks,
            reasoning=f"{reasoning}\n\nProchaine observation utile : {next_step}",
            rounds=rounds,
            recommend_human_review=True,
            **totals(usages),
        )
        self.tracer.emit(
            incident.id,
            "split",
            "verdict",
            cause=None,
            confidence=0.0,
            consensus=decision.kind.value,
            tracks=[track.cause.value for track in tracks],
            rounds=rounds,
            llm_calls=verdict.llm_calls,
            usd=verdict.usd,
        )
        return {"verdict": verdict, "usages": [usage]}

"""Cablage LangGraph : fan-out vers trois specialistes, fan-in, routage, boucle.

    START ─┬─> infra   ─┐
           ├─> app     ─┼─> route ─┬─> conclude ──> END
           └─> history ─┘    ▲     ├─> clarify ──┘ (retour vers route)
                             └─────┘     └─> split ──> END

La decision de routage n'est PAS stockee dans l'etat : chaque noeud la recalcule
avec `decide(...)`. C'est une fonction pure et bon marche, et un etat qui porte
une decision derivee finit toujours par porter une decision perimee -- ici, apres
une relance qui vient justement de changer les hypotheses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

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
from council.orchestration.routing import Route, decide, latest_by_agent
from council.orchestration.state import InvestigationState
from council.orchestration.trace import Tracer


def _totals(usages: list[CallUsage]) -> dict[str, Any]:
    return {
        "llm_calls": len(usages),
        "input_tokens": sum(u.input_tokens for u in usages),
        "output_tokens": sum(u.output_tokens for u in usages),
        "usd": sum(u.usd for u in usages),
        "latency_ms": sum(u.latency_ms for u in usages),
    }


def build_graph(
    specialists: Sequence[BaseSpecialist],
    arbiter: Arbiter,
    client: LLMClient,
    tracer: Tracer,
    effort_specialist: str = "low",
    max_rounds: int = 2,
) -> Any:
    by_name: dict[SpecialistName, BaseSpecialist] = {s.name: s for s in specialists}

    def specialist_node(name: SpecialistName) -> Callable[[InvestigationState], dict[str, Any]]:
        def node(state: InvestigationState) -> dict[str, Any]:
            incident: Incident = state["incident"]
            hypothesis, usage = by_name[name].analyse(incident, client, effort_specialist)
            tracer.emit(
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

    def route_node(state: InvestigationState) -> dict[str, Any]:
        incident: Incident = state["incident"]
        rounds = state.get("rounds", 0)
        decision = decide(state["hypotheses"], rounds, max_rounds)
        tracer.emit(
            incident.id,
            "route",
            "routing",
            route=decision.route.value,
            kind=decision.kind.value,
            leading_cause=None if decision.leading_cause is None else decision.leading_cause.value,
            support=decision.support,
            answered=decision.answered,
            abstained=decision.abstained,
            divergent=None if decision.divergent is None else decision.divergent.value,
            rounds_used=rounds,
            reason=decision.reason,
        )
        return {"route": decision.route.value}

    def clarify_node(state: InvestigationState) -> dict[str, Any]:
        incident: Incident = state["incident"]
        rounds = state.get("rounds", 0)
        decision = decide(state["hypotheses"], rounds, max_rounds)
        assert decision.divergent is not None
        current = latest_by_agent(state["hypotheses"])
        round_index = rounds + 1

        question, question_usage = arbiter.formulate_question(
            incident.id, current, decision, client, round_index
        )
        before = current[decision.divergent]
        revised, answer_usage = by_name[decision.divergent].reask(
            incident, client, effort_specialist, question, round_index
        )
        clarification = Clarification(
            round_index=round_index,
            target=decision.divergent,
            question=question,
            answer_cause=revised.cause,
            answer_confidence=revised.confidence,
            changed_mind=revised.cause is not before.cause,
        )
        tracer.emit(
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

    def conclude_node(state: InvestigationState) -> dict[str, Any]:
        incident: Incident = state["incident"]
        rounds = state.get("rounds", 0)
        decision = decide(state["hypotheses"], rounds, max_rounds)
        current = latest_by_agent(state["hypotheses"])
        cause, confidence, rejected, reasoning, usage = arbiter.synthesize(
            incident.id, current, decision, client
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
            **_totals(usages),
        )
        tracer.emit(
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

    def split_node(state: InvestigationState) -> dict[str, Any]:
        incident: Incident = state["incident"]
        rounds = state.get("rounds", 0)
        decision = decide(state["hypotheses"], rounds, max_rounds)
        current = latest_by_agent(state["hypotheses"])
        tracks, next_step, reasoning, usage = arbiter.report_split(
            incident.id, current, decision, client
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
            **_totals(usages),
        )
        tracer.emit(
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

    graph: Any = StateGraph(InvestigationState)
    graph.add_node("infra", specialist_node(SpecialistName.INFRA))
    graph.add_node("app", specialist_node(SpecialistName.APP))
    graph.add_node("history", specialist_node(SpecialistName.HISTORY))
    graph.add_node("route", route_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("conclude", conclude_node)
    graph.add_node("split", split_node)

    # Fan-out : trois aretes depuis START, executees dans le meme super-pas.
    for name in ("infra", "app", "history"):
        graph.add_edge(START, name)
        # Fan-in : `route` attend les trois avant de s'executer.
        graph.add_edge(name, "route")

    graph.add_conditional_edges(
        "route",
        lambda state: str(state["route"]),
        {
            Route.CONCLUDE.value: "conclude",
            Route.CLARIFY.value: "clarify",
            Route.REPORT_SPLIT.value: "split",
        },
    )
    graph.add_edge("clarify", "route")
    graph.add_edge("conclude", END)
    graph.add_edge("split", END)
    return graph.compile()


def investigate(graph: Any, incident: Incident) -> Verdict:
    final: dict[str, Any] = graph.invoke(
        {"incident": incident, "hypotheses": [], "clarifications": [], "usages": [], "rounds": 0}
    )
    verdict: Verdict = final["verdict"]
    return verdict

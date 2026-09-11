"""Le graphe complet, de bout en bout, sans reseau.

Le client simule repond en fonction du `tag` de l'appel, ce qui permet de
scenariser exactement la situation a tester : unanimite, majorite qui se rallie,
majorite qui s'entete, desaccord total.
"""

from __future__ import annotations

from typing import Any

import pytest

from council.agents.app import AppSpecialist
from council.agents.arbiter import Arbiter
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.retrieval import CaseRetriever
from council.data.taxonomy import RootCause
from council.llm.client import FakeClient
from council.models import ConsensusKind, Dataset
from council.orchestration.graph import build_graph, investigate
from council.orchestration.trace import Tracer, render_reasoning


def specialist_answer(cause: str | None, confidence: float = 0.8) -> dict[str, Any]:
    return {
        "cause": cause if cause is not None else "insufficient_evidence",
        "confidence": confidence,
        "evidence": ["observation a", "observation b"],
        "alternatives": [],
        "reasoning": "parce que.",
    }


def arbiter_verdict(cause: str, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "cause": cause,
        "confidence": confidence,
        "rejected": [{"cause": "memory_leak", "reason": "aucune preuve citee"}],
        "reasoning": "les preuves convergent.",
    }


ARBITER_QUESTION = {"question": "Vois-tu une montee monotone ?", "rationale": "pour trancher."}
ARBITER_SPLIT = {
    "tracks": [
        {"cause": "disk_full", "confidence": 0.4, "summary": "piste infra"},
        {"cause": "memory_leak", "confidence": 0.35, "summary": "piste appli"},
        {"cause": "cert_expiry", "confidence": 0.25, "summary": "piste historique"},
    ],
    "next_step": "verifier la date de validite du certificat.",
    "reasoning": "rien ne converge.",
}


class Scripted:
    """Repond selon le tag ; compte les relances pour simuler un agent qui cede ou non."""

    def __init__(self, answers: dict[str, str | None], relents_at: int | None = None) -> None:
        self.answers = answers
        self.relents_at = relents_at
        self.reask_count = 0

    def __call__(self, *, system: str, user: str, tag: str) -> dict[str, Any]:
        if tag.startswith("arbiter:question"):
            return ARBITER_QUESTION
        if tag.startswith("arbiter:split"):
            return ARBITER_SPLIT
        if tag.startswith("arbiter:synthesize"):
            return arbiter_verdict("disk_full")
        agent = tag.split(":")[0]
        if ":r" in tag:  # relance
            self.reask_count += 1
            if self.relents_at is not None and self.reask_count >= self.relents_at:
                return specialist_answer("disk_full")
            return specialist_answer(self.answers[agent])
        return specialist_answer(self.answers[agent])


def _graph(
    client: FakeClient, retriever: CaseRetriever, tracer: Tracer, max_rounds: int = 2
) -> Any:
    return build_graph(
        specialists=[InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=5)],
        arbiter=Arbiter(effort="high"),
        client=client,
        tracer=tracer,
        max_rounds=max_rounds,
    )


def test_unanimite_conclut_en_quatre_appels(dataset: Dataset, retriever: CaseRetriever) -> None:
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "disk_full", "history": "disk_full"})
    )
    tracer = Tracer(run_id="test")
    verdict = investigate(_graph(client, retriever, tracer), dataset.incidents[0])

    assert verdict.cause is RootCause.DISK_FULL
    assert verdict.consensus is ConsensusKind.UNANIMOUS
    assert verdict.rounds == 0
    assert verdict.llm_calls == 4, "3 specialistes + 1 arbitre"
    assert verdict.rejected, "l'arbitre doit dire ce qu'il ecarte"
    assert verdict.recommend_human_review is False


def test_la_majorite_relance_le_divergent_qui_se_rallie(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "disk_full", "history": "memory_leak"}, relents_at=1)
    )
    tracer = Tracer(run_id="test")
    verdict = investigate(_graph(client, retriever, tracer), dataset.incidents[0])

    assert verdict.rounds == 1
    assert verdict.consensus is ConsensusKind.UNANIMOUS, "le divergent s'est rallie"
    assert verdict.llm_calls == 6, "3 specialistes + question + relance + arbitre"
    clarifications = [r for r in tracer.records if r["event"] == "clarification"]
    assert len(clarifications) == 1
    assert clarifications[0]["changed_mind"] is True


def test_le_divergent_qui_s_entete_est_relance_deux_fois_puis_on_tranche(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    """Le plafond de relances est la garantie qu'une boucle ne peut pas s'emballer."""
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "disk_full", "history": "memory_leak"})
    )
    tracer = Tracer(run_id="test")
    verdict = investigate(_graph(client, retriever, tracer), dataset.incidents[0])

    assert verdict.rounds == 2
    assert verdict.consensus is ConsensusKind.MAJORITY
    assert verdict.cause is RootCause.DISK_FULL
    assert verdict.llm_calls == 8, "3 + 2 relances a 2 appels + 1 arbitre"
    assert verdict.confidence <= 0.75, "plafond structurel de la majorite"
    assert verdict.recommend_human_review is True


@pytest.mark.parametrize("max_rounds", [0, 1, 3])
def test_le_plafond_de_relances_est_respecte(
    dataset: Dataset, retriever: CaseRetriever, max_rounds: int
) -> None:
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "disk_full", "history": "memory_leak"})
    )
    tracer = Tracer(run_id="test")
    verdict = investigate(
        _graph(client, retriever, tracer, max_rounds=max_rounds), dataset.incidents[0]
    )
    assert verdict.rounds == max_rounds


def test_desaccord_total_ne_force_aucun_choix(dataset: Dataset, retriever: CaseRetriever) -> None:
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "memory_leak", "history": "cert_expiry"})
    )
    tracer = Tracer(run_id="test")
    verdict = investigate(_graph(client, retriever, tracer), dataset.incidents[0])

    assert verdict.cause is None, "pas de consensus n'est pas un echec, c'est la reponse"
    assert verdict.consensus is ConsensusKind.SPLIT
    assert len(verdict.tracks) == 3
    assert verdict.recommend_human_review is True
    assert verdict.llm_calls == 4, "aucune relance sur un desaccord total"


def test_une_seule_voix_est_plafonnee(dataset: Dataset, retriever: CaseRetriever) -> None:
    """L'arbitre annonce 0,9 ; la forme de l'accord ne le permet pas."""
    client = FakeClient(Scripted({"infra": None, "app": None, "history": "disk_full"}))
    tracer = Tracer(run_id="test")
    verdict = investigate(_graph(client, retriever, tracer), dataset.incidents[0])

    assert verdict.consensus is ConsensusKind.SINGLE_SOURCE
    assert verdict.confidence == pytest.approx(0.60)
    assert verdict.recommend_human_review is True


def test_la_trace_reconstitue_le_raisonnement(dataset: Dataset, retriever: CaseRetriever) -> None:
    client = FakeClient(
        Scripted({"infra": "disk_full", "app": "disk_full", "history": "memory_leak"}, relents_at=1)
    )
    tracer = Tracer(run_id="test")
    incident = dataset.incidents[0]
    investigate(_graph(client, retriever, tracer), incident)

    events = [r["event"] for r in tracer.records]
    assert events.count("hypothesis") == 3
    assert "routing" in events and "clarification" in events and "verdict" in events
    for record in tracer.records:
        if record["event"] == "routing":
            assert len(record["reason"]) > 20, "la trace doit dire POURQUOI"

    rendered = render_reasoning(tracer.records, incident.id)
    assert incident.id in rendered
    assert "relance" in rendered
    assert "disk_full" in rendered

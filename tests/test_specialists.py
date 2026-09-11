"""Les trois specialistes, isoles, sans reseau.

Le test qui compte le plus est `test_aucune_invite_ne_contient_la_verite` : il ne
verifie pas que les vues sont etanches en theorie, mais que ce qui part
reellement vers l'API ne contient ni la cause, ni le leurre, ni la categorie.
Une fuite a cet endroit ne se verrait nulle part dans les resultats -- ils
seraient simplement excellents.
"""

from __future__ import annotations

from typing import Any

import pytest

from council.agents.app import AppSpecialist
from council.agents.base import Specialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.retrieval import CaseRetriever
from council.data.taxonomy import Category, RootCause
from council.llm.client import FakeClient
from council.models import Dataset, SpecialistName

ANSWER: dict[str, Any] = {
    "cause": "disk_full",
    "confidence": 0.72,
    "evidence": ["disque a 99,4 % a la minute 55", "montee monotone depuis la minute 0"],
    "alternatives": ["cpu_saturation", "memory_leak", "cert_expiry"],
    "reasoning": "Le disque monte de facon monotone.",
}

ABSTENTION: dict[str, Any] = {
    "cause": "insufficient_evidence",
    "confidence": 0.9,
    "evidence": [],
    "alternatives": [],
    "reasoning": "Rien d'exploitable.",
}


def _fake(payload: dict[str, Any]) -> FakeClient:
    return FakeClient(lambda **_: payload)


def _specialists(retriever: CaseRetriever) -> list[Specialist]:
    return [InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=5)]


def test_la_reponse_est_convertie_en_hypothese(dataset: Dataset) -> None:
    client = _fake(ANSWER)
    hypothesis, usage = InfraSpecialist().analyse(dataset.incidents[0], client, "low")
    assert hypothesis.agent is SpecialistName.INFRA
    assert hypothesis.cause is RootCause.DISK_FULL
    assert hypothesis.confidence == pytest.approx(0.72)
    assert len(hypothesis.evidence) == 2
    assert usage.usd == 0.0


def test_les_alternatives_sont_plafonnees_a_deux(dataset: Dataset) -> None:
    hypothesis, _ = InfraSpecialist().analyse(dataset.incidents[0], _fake(ANSWER), "low")
    assert len(hypothesis.alternatives) == 2
    assert hypothesis.ranked()[0] is RootCause.DISK_FULL
    assert len(hypothesis.ranked()) == 3


def test_une_abstention_ne_peut_pas_etre_confiante(dataset: Dataset) -> None:
    """Sinon une absence de donnees polluerait la calibration comme une certitude."""
    hypothesis, _ = InfraSpecialist().analyse(dataset.incidents[0], _fake(ABSTENTION), "low")
    assert hypothesis.abstained
    assert hypothesis.cause is None
    assert hypothesis.confidence == 0.0
    assert hypothesis.ranked() == []


def test_chaque_agent_ne_recoit_que_sa_vue(dataset: Dataset, retriever: CaseRetriever) -> None:
    incident = next(i for i in dataset.incidents if i.category is Category.APP_PURE)
    log_message = incident.logs.lines[0].message

    infra_client = _fake(ANSWER)
    InfraSpecialist().analyse(incident, infra_client, "low")
    infra_prompt = infra_client.calls[0].user
    assert "cpu_pct" in infra_prompt
    assert log_message not in infra_prompt

    app_client = _fake(ANSWER)
    AppSpecialist().analyse(incident, app_client, "low")
    app_prompt = app_client.calls[0].user
    assert log_message in app_prompt
    assert "cpu_pct" not in app_prompt

    history_client = _fake(ANSWER)
    HistorySpecialist(retriever, k=5).analyse(incident, history_client, "low")
    history_prompt = history_client.calls[0].user
    assert "fiches_candidates" in history_prompt
    assert "cpu_pct" not in history_prompt


def test_aucune_invite_ne_contient_la_verite(dataset: Dataset, retriever: CaseRetriever) -> None:
    client = _fake(ANSWER)
    for incident in dataset.incidents:
        for specialist in _specialists(retriever):
            specialist.analyse(incident, client, "low")

    by_incident = {incident.id: incident for incident in dataset.incidents}
    for recorded in client.calls:
        incident_id = recorded.tag.split(":")[1]
        incident = by_incident[incident_id]
        emitted = (recorded.system + recorded.user).lower()
        # La liste fermee des causes figure dans les consignes : c'est normal et
        # identique pour les 45 incidents. Ce qui est interdit, c'est de pouvoir
        # distinguer CET incident -- donc les champs de verite terrain.
        assert "dominance" not in emitted, recorded.tag
        assert incident.category.value not in emitted, recorded.tag
        assert "root_cause" not in emitted.replace('"cause_retenue"', ""), recorded.tag


def test_l_agent_historique_sert_bien_k_fiches(dataset: Dataset, retriever: CaseRetriever) -> None:
    for k in (3, 5):
        client = _fake(ANSWER)
        HistorySpecialist(retriever, k=k).analyse(dataset.incidents[0], client, "low")
        assert client.calls[0].user.count('"id": "KB-') == k


def test_le_catalogue_des_causes_est_complet_dans_les_consignes() -> None:
    """Une cause absente des consignes serait invisible pour tous les agents."""
    from council.agents.infra import SYSTEM

    for cause in RootCause:
        assert cause.value in SYSTEM
    assert "insufficient_evidence" in SYSTEM

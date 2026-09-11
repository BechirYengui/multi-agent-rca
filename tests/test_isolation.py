"""Etancheite des vues : non negociable.

Si la verite terrain, le leurre ou la categorie atteignaient un agent, tout le
benchmark serait invalide -- et l'erreur serait invisible dans les resultats,
qui seraient simplement tres bons.
"""

from __future__ import annotations

import json

from council.data.taxonomy import Category
from council.models import Dataset

FORBIDDEN_FIELDS = ("root_cause", "decoy_cause", "category", "dominance_note")


def _serialized(view: object) -> str:
    return json.dumps(view, ensure_ascii=False, default=str).lower()


def test_aucune_vue_ne_contient_la_verite_terrain(dataset: Dataset) -> None:
    for incident in dataset.incidents:
        for view in (incident.infra_view(), incident.app_view()):
            payload = _serialized(view)
            for field in FORBIDDEN_FIELDS:
                assert field not in payload, (incident.id, field)
            assert incident.root_cause.value not in payload, incident.id
            if incident.decoy_cause is not None:
                assert incident.decoy_cause.value not in payload, incident.id
            assert incident.category.value not in payload, incident.id


def test_la_vue_infra_ne_contient_pas_les_journaux(dataset: Dataset) -> None:
    for incident in dataset.incidents:
        assert "logs" not in incident.infra_view()
        assert "metrics" in incident.infra_view()


def test_la_vue_applicative_ne_contient_pas_les_metriques(dataset: Dataset) -> None:
    for incident in dataset.incidents:
        assert "metrics" not in incident.app_view()
        assert "logs" in incident.app_view()


def test_la_requete_historique_ne_contient_ni_metriques_ni_traces(dataset: Dataset) -> None:
    """L'agent Historique ne doit pas pouvoir refaire le travail des deux autres."""
    for incident in dataset.incidents:
        query = incident.history_query()
        assert "cpu_pct" not in query
        for trace in incident.logs.traces:
            assert trace.exception not in query


def test_le_motif_distinctif_atteint_bien_la_requete_historique(dataset: Dataset) -> None:
    """Symetrique du test precedent : l'isolement ne doit pas rendre l'agent aveugle."""
    history = [i for i in dataset.incidents if i.category is Category.HISTORY_REQUIRED]
    for incident in history:
        fingerprints = [line.message for line in incident.logs.lines if line.level == "ERROR"]
        assert any(len(message) > 60 for message in fingerprints), incident.id
        assert any(message in incident.history_query() for message in fingerprints), incident.id

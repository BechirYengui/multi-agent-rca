"""Recherche de cas passes : la mesure qui decide BM25 vs embeddings."""

from __future__ import annotations

import pytest

from council.agents.retrieval import CaseRetriever
from council.models import Dataset


def test_la_recherche_renvoie_k_resultats_ordonnes(
    retriever: CaseRetriever, dataset: Dataset
) -> None:
    results = retriever.search(dataset.incidents[0].history_query(), k=5)
    assert len(results) == 5
    scores = [case.score for case in results]
    assert scores == sorted(scores, reverse=True)


def test_le_rappel_croit_avec_k(
    retriever: CaseRetriever, dataset: Dataset, matches: dict[str, str]
) -> None:
    queries = {incident.id: incident.history_query() for incident in dataset.incidents}
    values = [retriever.recall_at_k(matches, queries, k) for k in (1, 3, 5)]
    assert values == sorted(values)


@pytest.mark.parametrize(("k", "minimum"), [(1, 0.45), (3, 0.60), (5, 0.75)])
def test_rappel_mesure_non_regression(
    retriever: CaseRetriever, dataset: Dataset, matches: dict[str, str], k: int, minimum: float
) -> None:
    """Bornes basses figees sur la mesure du 2026-09-11 (54,5 / 63,6 / 81,8 %).

    Elles ne sont pas un objectif de qualite : elles interdisent seulement qu'une
    retouche des gabarits degrade la recherche sans qu'on s'en apercoive.
    """
    queries = {incident.id: incident.history_query() for incident in dataset.incidents}
    assert retriever.recall_at_k(matches, queries, k) >= minimum

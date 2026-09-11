"""Le plancher deterministe : ordre des regles et reproductibilite."""

from __future__ import annotations

from council.agents.keyword import DEFAULT_CAUSE, classify
from council.agents.retrieval import CaseRetriever
from council.data.taxonomy import Category, RootCause
from council.models import Dataset


def test_un_pic_de_trafic_n_est_pas_classe_en_saturation_cpu(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    """Regression : un pic de trafic fait TOUJOURS monter le CPU.

    Si la regle CPU passait avant la regle trafic, les huit incidents de pic de
    trafic seraient classes en saturation CPU et le plancher paraitrait
    faussement mauvais sur une categorie et faussement bon sur l'autre.
    """
    spikes = [
        i
        for i in dataset.incidents
        if i.category is Category.INFRA_PURE and i.root_cause is RootCause.TRAFFIC_SPIKE
    ]
    assert spikes
    for incident in spikes:
        assert classify(incident, retriever).cause is RootCause.TRAFFIC_SPIKE, incident.id


def test_le_plancher_est_deterministe(dataset: Dataset, retriever: CaseRetriever) -> None:
    first = [classify(i, retriever).cause for i in dataset.incidents]
    second = [classify(i, retriever).cause for i in dataset.incidents]
    assert first == second


def test_sans_aucun_signal_le_plancher_se_replie(dataset: Dataset) -> None:
    """Sans recherche historique, les incidents muets tombent sur le repli."""
    muets = [i for i in dataset.incidents if i.category is Category.HISTORY_REQUIRED]
    for incident in muets:
        assert classify(incident, None).cause is DEFAULT_CAUSE, incident.id


def test_le_plancher_resout_les_incidents_infra(dataset: Dataset, retriever: CaseRetriever) -> None:
    """Fait mesure, a garder sous les yeux : l'infra pure est resoluble sans LLM.

    Ce n'est pas un defaut du jeu de donnees, c'est la realite de ces incidents.
    Consequence a assumer dans le rapport : un eventuel gain du multi-agents ne
    peut pas venir de cette categorie.
    """
    infra = [i for i in dataset.incidents if i.category is Category.INFRA_PURE]
    hits = sum(classify(i, retriever).cause is i.root_cause for i in infra)
    assert hits == len(infra)

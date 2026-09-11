"""Les trois gardes anti-triche, en tests.

Ces tests sont la raison pour laquelle on peut croire les chiffres du benchmark.
S'ils tombent, le jeu de donnees ne prouve plus rien et il faut le corriger AVANT
de relancer un run facture.
"""

from __future__ import annotations

from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.data.audit import (
    FLOOR_MAX,
    FLOOR_MIN,
    JACCARD_MAX_MEDIAN,
    audit,
    log_families,
    metric_signals,
)
from council.data.taxonomy import ALL_FAMILY_TOKENS, FAMILY_OF, Category
from council.data.templates import NEUTRAL_LINES
from council.models import Dataset, KnowledgeBase
from council.text import token_set


def test_garde_1_aucune_fuite_de_signal(
    dataset: Dataset, kb: KnowledgeBase, matches: dict[str, str]
) -> None:
    report = audit(dataset, kb, matches)
    assert report.leaks == [], [f"{f.incident_id} {f.rule} {f.detail}" for f in report.leaks]


def test_garde_1_bis_les_vues_neutres_le_sont_vraiment(dataset: Dataset) -> None:
    """Detail du garde 1, categorie par categorie, pour que l'echec soit lisible."""
    for incident in dataset.incidents:
        signals = metric_signals(incident.metrics)
        families = log_families(incident.logs)
        if incident.category is Category.INFRA_PURE:
            assert signals, incident.id
            assert not families, (incident.id, families)
        elif incident.category is Category.APP_PURE:
            assert not signals, (incident.id, signals)
            assert families == {FAMILY_OF[incident.root_cause]}, incident.id
        elif incident.category is Category.HISTORY_REQUIRED:
            assert not signals, (incident.id, signals)
            assert not families, (incident.id, families)
        else:
            assert signals, incident.id
            assert families == {FAMILY_OF[incident.root_cause]}, incident.id
            assert incident.decoy_cause is not None
            assert FAMILY_OF[incident.decoy_cause] is not FAMILY_OF[incident.root_cause]


def test_les_gabarits_neutres_ne_contiennent_aucun_token_de_famille() -> None:
    """Sans cela, la neutralite des vues dependrait du tirage aleatoire."""
    for _, template in NEUTRAL_LINES:
        assert not (token_set(template) & ALL_FAMILY_TOKENS), template


def test_garde_2_pas_de_recopie_depuis_la_base_historique(
    dataset: Dataset, kb: KnowledgeBase, matches: dict[str, str]
) -> None:
    report = audit(dataset, kb, matches)
    assert report.jaccard_median < JACCARD_MAX_MEDIAN, report.jaccard_values
    assert report.jaccard_max < 0.45, report.jaccard_values


def test_garde_3_le_jeu_n_est_ni_trivial_ni_impossible(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    hits = sum(
        classify(incident, retriever).cause is incident.root_cause for incident in dataset.incidents
    )
    accuracy = hits / len(dataset.incidents)
    assert FLOOR_MIN <= accuracy <= FLOOR_MAX, (
        f"plancher deterministe a {accuracy:.1%} : hors de la bande "
        f"[{FLOOR_MIN:.0%}, {FLOOR_MAX:.0%}]. Au-dessus, le jeu est resoluble sans "
        f"LLM et le benchmark ne prouve rien ; en dessous, il est bruite au point "
        f"qu'aucun signal n'est exploitable."
    )


def test_les_cas_ambigus_mettent_bien_le_plancher_en_defaut(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    """Le plancher suit les metriques, qui portent le leurre : il doit se tromper.

    Si ce test devient faux, c'est que les cas ambigus ne le sont plus.
    """
    ambiguous = [i for i in dataset.incidents if i.category is Category.AMBIGUOUS]
    hits = sum(classify(i, retriever).cause is i.root_cause for i in ambiguous)
    assert hits / len(ambiguous) <= 0.20

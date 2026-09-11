"""Le jeu de donnees est un artefact publie : il doit etre reproductible."""

from __future__ import annotations

import json

from council.config import INCIDENTS_PATH, KB_PATH
from council.data.generator import build_dataset, expected_counts
from council.data.taxonomy import Category, RootCause
from council.models import Dataset, KnowledgeBase


def test_determinisme_octet_pour_octet() -> None:
    first = build_dataset().model_dump_json()
    second = build_dataset().model_dump_json()
    assert first == second


def test_le_fichier_versionne_correspond_au_generateur(dataset: Dataset, kb: KnowledgeBase) -> None:
    """Garde-fou contre le pire scenario : generateur modifie, fichier pas regenere.

    Les chiffres publies dans docs/ et dans le README viennent du FICHIER.
    S'il diverge du code, tout le reste ment.
    """
    on_disk = json.loads(INCIDENTS_PATH.read_text(encoding="utf-8"))
    assert on_disk == dataset.model_dump(mode="json"), "lancer `make dataset`"
    kb_on_disk = json.loads(KB_PATH.read_text(encoding="utf-8"))
    assert kb_on_disk == kb.model_dump(mode="json"), "lancer `make dataset`"


def test_repartition_des_categories(dataset: Dataset) -> None:
    assert len(dataset.incidents) == 45
    counts = expected_counts()
    assert counts == {
        Category.INFRA_PURE: 12,
        Category.APP_PURE: 12,
        Category.HISTORY_REQUIRED: 11,
        Category.AMBIGUOUS: 10,
    }


def test_identifiants_uniques(dataset: Dataset, kb: KnowledgeBase) -> None:
    assert len({i.id for i in dataset.incidents}) == len(dataset.incidents)
    assert len({e.id for e in kb.entries}) == len(kb.entries)


def test_toutes_les_causes_sont_representees(dataset: Dataset) -> None:
    """Une cause jamais utilisee comme verite terrain fausserait le taux par cause."""
    used = {incident.root_cause for incident in dataset.incidents}
    assert used == set(RootCause)


def test_chaque_incident_historique_a_sa_fiche(
    dataset: Dataset, kb: KnowledgeBase, matches: dict[str, str]
) -> None:
    by_id = {entry.id: entry for entry in kb.entries}
    history = [i for i in dataset.incidents if i.category is Category.HISTORY_REQUIRED]
    assert len(history) == 11
    for incident in history:
        entry = by_id[matches[incident.id]]
        assert entry.root_cause is incident.root_cause


def test_base_historique_complete(kb: KnowledgeBase, matches: dict[str, str]) -> None:
    assert len(kb.entries) == 30
    # 11 fiches utiles + 19 distracteurs : sans distracteurs, retrouver le bon
    # cas serait trivial et le rappel mesure ne voudrait rien dire.
    assert len(set(matches.values())) == 11

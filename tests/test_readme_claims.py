"""Chaque chiffre affiché par le README est recalculé ici.

C'est la seule défense contre la dérive la plus banale d'un dépôt de
démonstration : le code évolue, les chiffres de la vitrine restent ceux du
premier jour, et plus personne ne s'en aperçoit. Ici, **un README qui ment
devient un test rouge**.

Les valeurs ne sont pas recopiées dans le test : elles sont extraites du fichier
README puis confrontées à ce que produit le code. Corriger l'un sans l'autre
échoue dans les deux sens.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from council.agents.app import AppSpecialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.benchmark.estimate import estimate_benchmark
from council.config import PROJECT_ROOT
from council.data.audit import audit
from council.data.taxonomy import CAUSES_OF_FAMILY, Category, RootCause, SymptomFamily
from council.models import Dataset, KnowledgeBase

README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def claim(pattern: str) -> str:
    """Extrait une affirmation du README, ou echoue en disant laquelle manque."""
    found = re.search(pattern, README)
    assert found is not None, f"affirmation introuvable dans le README : {pattern}"
    return found.group(1)


def as_pct(text: str) -> float:
    return float(text.replace(",", ".")) / 100


# --------------------------------------------------------------------------- #
# Volumetrie
# --------------------------------------------------------------------------- #


def test_le_nombre_d_incidents_annonce(dataset: Dataset) -> None:
    assert int(claim(r"(\d+) incidents synthétiques")) == len(dataset.incidents)


def test_le_nombre_de_causes_annonce() -> None:
    assert int(claim(r"(\d+) causes racines")) == len(RootCause)


def test_les_familles_annoncees() -> None:
    found = re.search(r"\*\*(\d+) familles de (\d+)\*\*", README)
    assert found is not None, "le README n'annonce pas la structure en familles"
    assert int(found.group(1)) == len(SymptomFamily)
    for causes in CAUSES_OF_FAMILY.values():
        assert len(causes) == int(found.group(2))


def test_la_repartition_par_categorie_du_tableau(dataset: Dataset) -> None:
    for category in Category:
        annonce = int(claim(rf"\| `{category.value}` \| (\d+) \|"))
        reel = sum(1 for i in dataset.incidents if i.category is category)
        assert annonce == reel, category


# --------------------------------------------------------------------------- #
# Les trois gardes
# --------------------------------------------------------------------------- #


def test_la_fuite_de_signal_annoncee(
    dataset: Dataset, kb: KnowledgeBase, matches: dict[str, str]
) -> None:
    found = re.search(r"\*\*(\d+) / (\d+)\*\*", README)
    assert found is not None, "le README n'annonce pas le resultat du garde anti-fuite"
    fuites, total = int(found.group(1)), int(found.group(2))
    report = audit(dataset, kb, matches)
    assert fuites == len(report.leaks) == 0
    assert total == len(dataset.incidents)


def test_le_jaccard_median_annonce(
    dataset: Dataset, kb: KnowledgeBase, matches: dict[str, str]
) -> None:
    annonce = float(claim(r"Jaccard médian ([\d,]+)\*\*").replace(",", "."))
    report = audit(dataset, kb, matches)
    assert report.jaccard_median == pytest.approx(annonce, abs=5e-4)


def test_le_plancher_annonce(dataset: Dataset, retriever: CaseRetriever) -> None:
    annonce = as_pct(claim(r"\*\*([\d,]+) %\*\* — bande"))
    hits = sum(
        classify(incident, retriever).cause is incident.root_cause for incident in dataset.incidents
    )
    assert hits / len(dataset.incidents) == pytest.approx(annonce, abs=5e-4)


def test_le_plancher_a_100_pour_cent_sur_l_infra_pure(
    dataset: Dataset, retriever: CaseRetriever
) -> None:
    annonce = as_pct(claim(r"\*\*([\d,]+) % sur les incidents d'infrastructure pure\*\*"))
    infra = [i for i in dataset.incidents if i.category is Category.INFRA_PURE]
    hits = sum(classify(i, retriever).cause is i.root_cause for i in infra)
    assert hits / len(infra) == pytest.approx(annonce, abs=5e-4)


def test_le_rappel_bm25_annonce(
    dataset: Dataset, retriever: CaseRetriever, matches: dict[str, str]
) -> None:
    annonces = claim(r"\*\*([\d,]+ % / [\d,]+ % / [\d,]+ %)\*\*").split(" / ")
    queries = {incident.id: incident.history_query() for incident in dataset.incidents}
    for k, annonce in zip((1, 3, 5), annonces, strict=True):
        mesure = retriever.recall_at_k(matches, queries, k)
        assert mesure == pytest.approx(as_pct(annonce.replace(" %", "")), abs=5e-4), k


# --------------------------------------------------------------------------- #
# Le coût
# --------------------------------------------------------------------------- #


def test_l_encadrement_de_cout_annonce(dataset: Dataset, retriever: CaseRetriever) -> None:
    """Le README annonce une fourchette en Sonnet 5 : elle doit sortir du chiffrage."""
    low_text, high_text = claim(r"\*\*([\d,]+ \$ à [\d,]+) \$\*\*").split(" $ à ")
    low = float(low_text.replace(",", "."))
    high = float(high_text.replace(",", "."))

    specialists = [InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=5)]
    with tempfile.TemporaryDirectory() as tmp:
        estimates = estimate_benchmark(dataset, retriever, specialists, out_dir=Path(tmp))
    values = sorted(estimate.usd("claude-sonnet-5") for estimate in estimates.values())
    assert values[0] == pytest.approx(low, abs=0.005)
    assert values[-1] == pytest.approx(high, abs=0.005)


# --------------------------------------------------------------------------- #
# Le nombre de tests, annonce deux fois dans le README
# --------------------------------------------------------------------------- #


def test_le_nombre_de_tests_annonce(request: pytest.FixtureRequest) -> None:
    collected = request.session.testscollected
    if collected < 50:
        pytest.skip("suite partielle : le compte n'a de sens que sur la suite complete")
    annonces = {int(value) for value in re.findall(r"\*\*(\d+) tests", README)}
    annonces |= {int(value) for value in re.findall(r"# (\d+) tests", README)}
    assert annonces, "le README n'annonce aucun nombre de tests"
    assert annonces == {collected}, f"README annonce {annonces}, la suite en collecte {collected}"

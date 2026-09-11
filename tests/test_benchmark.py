"""Le harnais complet sur les 45 incidents, avec un client simule. 0 $, 0 reseau.

C'est le test qui valide la tuyauterie AVANT de la brancher sur une API
facturee : quatre bras, ecriture incrementale, metriques, rapport, graphiques.
Les reponses sont scenarisees pour que chaque branche du routeur soit
effectivement empruntee.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from council.agents.app import AppSpecialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.retrieval import CaseRetriever
from council.benchmark.metrics import consensus_analysis, paired, summarize
from council.benchmark.plots import accuracy_by_category, consensus_vs_accuracy
from council.benchmark.report import render_benchmark_markdown
from council.benchmark.runner import BenchmarkRunner, pick_by_confidence, read_results
from council.budget import BudgetExceeded
from council.data.taxonomy import RootCause
from council.llm.client import FakeClient
from council.models import Dataset, Hypothesis, SpecialistName

OTHERS = [RootCause.MEMORY_LEAK, RootCause.CERT_EXPIRY, RootCause.NETWORK_PARTITION]


def _wrong(truth: RootCause, offset: int) -> str:
    pool = [c for c in OTHERS if c is not truth]
    return pool[offset % len(pool)].value


class Scenarios:
    """Cinq situations, reparties sur les 45 incidents : 9 de chaque.

    0 unanimite juste | 1 majorite juste, le divergent s'entete | 2 desaccord
    total | 3 une seule voix, juste | 4 unanimite fausse.
    """

    def __init__(self, dataset: Dataset) -> None:
        self.truth = {i.id: i.root_cause for i in dataset.incidents}
        self.scenario = {i.id: index % 5 for index, i in enumerate(dataset.incidents)}
        self.index = {i.id: index for index, i in enumerate(dataset.incidents)}

    def __call__(self, *, system: str, user: str, tag: str) -> dict[str, Any]:
        parts = tag.split(":")
        role = parts[0]
        incident_id = parts[-1].split("@")[0] if role == "arbiter" else parts[1]
        if role == "baseline":
            incident_id = parts[2]
        incident_id = next(p for p in parts if p.startswith("INC-"))
        truth = self.truth[incident_id]
        scenario = self.scenario[incident_id]

        if role == "arbiter":
            return self._arbiter(parts[1], incident_id, truth, scenario)
        if role == "baseline":
            correct = self.index[incident_id] % 2 == 0
            return _answer(truth.value if correct else _wrong(truth, 0), 0.7)
        return self._specialist(role, truth, scenario)

    def _specialist(self, role: str, truth: RootCause, scenario: int) -> dict[str, Any]:
        if scenario == 0:
            return _answer(truth.value, 0.85)
        if scenario == 1:
            return _answer(truth.value if role != "history" else _wrong(truth, 0), 0.8)
        if scenario == 2:
            mapping = {
                "infra": truth.value,
                "app": _wrong(truth, 0),
                "history": _wrong(truth, 1),
            }
            return _answer(mapping[role], 0.6)
        if scenario == 3:
            return _answer(truth.value if role == "history" else None, 0.75)
        return _answer(_wrong(truth, 0), 0.9)

    def _arbiter(
        self, task: str, incident_id: str, truth: RootCause, scenario: int
    ) -> dict[str, Any]:
        if task == "question":
            return {"question": "Une observation de plus ?", "rationale": "pour trancher."}
        if task == "split":
            return {
                "tracks": [
                    {"cause": truth.value, "confidence": 0.4, "summary": "piste 1"},
                    {"cause": _wrong(truth, 0), "confidence": 0.35, "summary": "piste 2"},
                ],
                "next_step": "verifier sur place.",
                "reasoning": "rien ne converge.",
            }
        retained = truth.value if scenario in (0, 1, 3) else _wrong(truth, 0)
        return {
            "cause": retained,
            "confidence": 0.9,
            "rejected": [{"cause": _wrong(truth, 1), "reason": "aucune preuve"}],
            "reasoning": "synthese.",
        }


def _answer(cause: str | None, confidence: float) -> dict[str, Any]:
    return {
        "cause": cause or "insufficient_evidence",
        "confidence": confidence,
        "evidence": ["a", "b"],
        "alternatives": [],
        "reasoning": "r",
    }


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[Any], Path]:
    from council.data.generator import build_dataset, build_knowledge_base

    dataset = build_dataset()
    retriever = CaseRetriever(build_knowledge_base().entries)
    # Repertoire neuf a chaque execution : `arms.jsonl` s'ecrit en ajout, un
    # repertoire persistant ferait grossir le fichier d'un run a l'autre.
    out_dir = tmp_path_factory.mktemp("bench") / "run"
    runner = BenchmarkRunner(
        dataset=dataset,
        retriever=retriever,
        specialists=[InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=5)],
        client=FakeClient(Scenarios(dataset)),
        run_id="TEST",
        out_dir=out_dir,
        baseline_efforts=("medium", "high"),
    )
    return runner.run(), out_dir


def test_les_quatre_bras_couvrent_les_45_incidents(bench: tuple[list[Any], Path]) -> None:
    results, _ = bench
    summaries = summarize(results)
    assert set(summaries) == {"floor", "baseline@medium", "baseline@high", "council", "vote"}
    assert all(summary.n == 45 for summary in summaries.values())


def test_le_plancher_retrouve_exactement_la_mesure_de_la_phase_1(
    bench: tuple[list[Any], Path],
) -> None:
    """Verrou entre les deux phases : le meme plancher doit donner le meme chiffre."""
    results, _ = bench
    assert summarize(results)["floor"].accuracy == pytest.approx(24 / 45, abs=1e-9)


def test_le_bras_vote_ne_coute_rien(bench: tuple[list[Any], Path]) -> None:
    """Il rejoue les hypotheses deja payees par le conseil : 0 appel, 0 dollar."""
    results, _ = bench
    vote = summarize(results)["vote"]
    assert vote.usd == 0.0
    assert vote.llm_calls == 0


def test_les_scenarios_produisent_les_taux_attendus(bench: tuple[list[Any], Path]) -> None:
    results, _ = bench
    summaries = summarize(results)
    # 3 scenarios justes sur 5 pour le conseil, 4 sur 5 pour le vote.
    assert summaries["council"].accuracy == pytest.approx(27 / 45)
    assert summaries["vote"].accuracy == pytest.approx(36 / 45)


def test_le_test_apparie_detecte_que_le_vote_bat_le_conseil(
    bench: tuple[list[Any], Path],
) -> None:
    """Exactement le resultat que le projet doit etre capable de publier."""
    results, _ = bench
    comparison = paired(results, "council", "vote")
    assert comparison.only_a == 0
    assert comparison.only_b == 9
    assert comparison.p_value < 0.01
    # La regle du seuil, posee avant le run, l'emporte sur une p-valeur basse :
    # le verdict reste « non concluant », et la p-valeur est affichee quand meme.
    assert comparison.conclusive is False
    assert "non concluant" in comparison.verdict
    assert "0.004" in comparison.verdict


def test_l_analyse_de_consensus_distingue_les_formes(bench: tuple[list[Any], Path]) -> None:
    results, _ = bench
    analysis = consensus_analysis(results)
    assert set(analysis.by_kind) >= {"unanimous", "majority", "split", "single_source"}
    # 9 unanimites justes, 9 fausses : l'accord ne predit alors RIEN, et la
    # mesure doit le dire plutot que de flatter la these du projet.
    assert analysis.unanimous_total == 18
    assert analysis.unanimous_accuracy == pytest.approx(0.5)
    assert analysis.convergence_predicts_correctness is False


def test_le_rapport_dit_la_verite_meme_quand_elle_derange(
    bench: tuple[list[Any], Path],
) -> None:
    results, _ = bench
    markdown = render_benchmark_markdown(results, run_id="TEST", model="fake", passes=1)
    assert "La convergence ne predit PAS l'exactitude" in markdown
    assert "council" in markdown and "vote" in markdown
    assert "McNemar" in markdown
    assert "Ce que ce benchmark ne dit pas" in markdown


def test_les_graphiques_sont_produits(bench: tuple[list[Any], Path], tmp_path: Path) -> None:
    results, _ = bench
    first = accuracy_by_category(results, tmp_path / "a.png")
    second = consensus_vs_accuracy(results, tmp_path / "b.png")
    assert first.stat().st_size > 5000
    assert second.stat().st_size > 5000


def test_les_lignes_sont_ecrites_au_fil_de_l_eau(bench: tuple[list[Any], Path]) -> None:
    _, out_dir = bench
    rows = read_results(out_dir / "arms.jsonl")
    assert len(rows) == 45 * 5
    assert {row.arm for row in rows} == {
        "floor",
        "baseline@medium",
        "baseline@high",
        "council",
        "vote",
    }


def test_un_depassement_de_budget_laisse_des_resultats_exploitables(tmp_path: Path) -> None:
    """Un plantage au 3e incident doit laisser 2 incidents utilisables, pas un fichier vide."""
    from council.data.generator import build_dataset, build_knowledge_base

    dataset = build_dataset()
    retriever = CaseRetriever(build_knowledge_base().entries)
    scenarios = Scenarios(dataset)
    calls = {"n": 0}

    def responder(**kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] > 12:
            raise BudgetExceeded("plafond atteint")
        return scenarios(**kwargs)

    runner = BenchmarkRunner(
        dataset=dataset,
        retriever=retriever,
        specialists=[InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=5)],
        client=FakeClient(responder),
        run_id="TEST-PARTIAL",
        out_dir=tmp_path / "partial",
        baseline_efforts=("high",),
    )
    results = runner.run()
    assert runner.partial is True
    assert results, "les incidents deja traites doivent etre conserves"
    assert (tmp_path / "partial" / "arms.jsonl").exists()


def test_l_agregation_triviale_est_deterministe() -> None:
    """A confiance egale, l'ordre des agents departage -- sinon le bras bougerait seul."""

    def h(agent: SpecialistName, cause: RootCause | None, confidence: float) -> Hypothesis:
        return Hypothesis(
            agent=agent,
            cause=cause,
            confidence=0.0 if cause is None else confidence,
            evidence=[],
            alternatives=[],
            reasoning="",
        )

    tie = [
        h(SpecialistName.INFRA, RootCause.DISK_FULL, 0.8),
        h(SpecialistName.APP, RootCause.MEMORY_LEAK, 0.8),
        h(SpecialistName.HISTORY, RootCause.CERT_EXPIRY, 0.8),
    ]
    assert pick_by_confidence(tie) is not None
    winner = pick_by_confidence(tie)
    assert winner is not None and winner.agent is SpecialistName.INFRA
    assert pick_by_confidence([h(SpecialistName.INFRA, None, 0.0)]) is None

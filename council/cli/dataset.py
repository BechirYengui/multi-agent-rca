"""Commandes `council dataset` : generer le jeu et recalculer ses gardes."""

from __future__ import annotations

import json
from collections import defaultdict

import typer

from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.cli.context import load_dataset, load_kb
from council.config import INCIDENTS_PATH, KB_PATH
from council.data.audit import FLOOR_MAX, FLOOR_MIN, JACCARD_MAX_MEDIAN, audit
from council.data.generator import build_dataset, build_knowledge_base
from council.data.specs import kb_matches
from council.data.taxonomy import Category
from council.models import Dataset

dataset_app = typer.Typer(help="Jeu de donnees synthetique", no_args_is_help=True)


@dataset_app.command("build")
def dataset_build() -> None:
    """Regenere le jeu de donnees. Deterministe : meme graine, memes octets."""
    dataset = build_dataset()
    kb = build_knowledge_base()
    INCIDENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    INCIDENTS_PATH.write_text(
        json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    KB_PATH.write_text(
        json.dumps(kb.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"{len(dataset.incidents)} incidents -> {INCIDENTS_PATH}")
    typer.echo(f"{len(kb.entries)} fiches historiques -> {KB_PATH}")


@dataset_app.command("audit")
def dataset_audit() -> None:
    """Recalcule les trois gardes anti-triche et le plancher deterministe."""
    dataset = load_dataset()
    kb = load_kb()
    matches = kb_matches()
    report = audit(dataset, kb, matches)
    retriever = CaseRetriever(kb.entries)

    typer.echo("\n== Garde 1 : fuite de signal entre les vues ==")
    if report.leaks:
        for leak in report.leaks:
            typer.echo(f"  FUITE {leak.incident_id}  {leak.rule}  {leak.detail}")
    else:
        typer.echo(f"  0 fuite sur {len(dataset.incidents)} incidents")

    typer.echo("\n== Garde 2 : recouvrement lexical avec la base historique ==")
    typer.echo(
        f"  Jaccard median {report.jaccard_median:.3f} "
        f"(max {report.jaccard_max:.3f}, seuil median < {JACCARD_MAX_MEDIAN})"
    )

    typer.echo("\n== Garde 3 : le jeu est-il trivial ? ==")
    without = _floor_accuracy(dataset, None)
    with_history = _floor_accuracy(dataset, retriever)
    typer.echo(f"  plancher sans historique : {without['global']:6.1%}")
    typer.echo(
        f"  plancher avec historique : {with_history['global']:6.1%} "
        f"(bande admissible {FLOOR_MIN:.0%} - {FLOOR_MAX:.0%}, hasard 25 %)"
    )
    for category in Category:
        typer.echo(f"    {category:<18} {with_history[category]:6.1%}")

    typer.echo("\n== Rappel de la recherche de cas passes (BM25) ==")
    queries = {inc.id: inc.history_query() for inc in dataset.incidents}
    for k in (1, 3, 5):
        typer.echo(f"  rappel@{k} : {retriever.recall_at_k(matches, queries, k):.1%}")

    verdict = report.ok and FLOOR_MIN <= with_history["global"] <= FLOOR_MAX
    typer.echo(
        "\n" + ("VERDICT : jeu de donnees exploitable" if verdict else "VERDICT : A CORRIGER")
    )
    raise typer.Exit(code=0 if verdict else 1)


def _floor_accuracy(dataset: Dataset, retriever: CaseRetriever | None) -> dict[str, float]:
    hits: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for incident in dataset.incidents:
        correct = int(classify(incident, retriever).cause is incident.root_cause)
        hits["global"] += correct
        total["global"] += 1
        hits[incident.category] += correct
        total[incident.category] += 1
    return {key: hits[key] / total[key] for key in total}

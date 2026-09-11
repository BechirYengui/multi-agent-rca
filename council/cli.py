"""Ligne de commande du projet."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

import typer

from council.agents.app import AppSpecialist
from council.agents.base import Specialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.benchmark.calibration import dry_run, run_calibration, summarize
from council.benchmark.report import render_markdown
from council.budget import BudgetExceeded, BudgetGuard
from council.config import (
    CACHE_DIR,
    INCIDENTS_PATH,
    KB_PATH,
    PROJECT_ROOT,
    RESULTS_DIR,
    load_settings,
)
from council.data.audit import FLOOR_MAX, FLOOR_MIN, JACCARD_MAX_MEDIAN, audit
from council.data.generator import build_dataset, build_knowledge_base
from council.data.specs import SPECS
from council.data.taxonomy import Category
from council.llm.client import AnthropicClient
from council.models import Dataset, KnowledgeBase

app = typer.Typer(help="incident-council", no_args_is_help=True)
dataset_app = typer.Typer(help="Jeu de donnees synthetique", no_args_is_help=True)
agents_app = typer.Typer(help="Les trois specialistes", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")
app.add_typer(agents_app, name="agents")


def build_specialists(retriever: CaseRetriever, k: int) -> list[Specialist]:
    return [InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=k)]


def kb_matches() -> dict[str, str]:
    return {spec.id: spec.kb_match for spec in SPECS if spec.kb_match}


def load_dataset() -> Dataset:
    return Dataset.model_validate_json(INCIDENTS_PATH.read_text(encoding="utf-8"))


def load_kb() -> KnowledgeBase:
    return KnowledgeBase.model_validate_json(KB_PATH.read_text(encoding="utf-8"))


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


if __name__ == "__main__":  # pragma: no cover
    app()


@agents_app.command("dry-run")
def agents_dry_run(
    k: int = typer.Option(5, help="Fiches candidates servies a l'agent Historique"),
    effort: str = typer.Option("low"),
    model: str = typer.Option("", help="Par defaut : COUNCIL_MODEL"),
) -> None:
    """Chiffre la calibration AVANT le premier appel facture. Aucun reseau."""
    settings = load_settings()
    chosen = model or settings.model
    dataset = load_dataset()
    specialists = build_specialists(CaseRetriever(load_kb().entries), k)
    estimate = dry_run(dataset, specialists, effort)

    typer.echo(f"modele                 {chosen}   (effort {effort}, k={k})")
    typer.echo(f"appels                 {estimate.calls}")
    typer.echo(f"jetons d'entree        {estimate.input_tokens:,} (estimes hors ligne)")
    typer.echo(f"jetons de sortie       {estimate.output_tokens:,} (hypothese 900/appel)")
    typer.echo(f"cout projete           {estimate.usd(chosen):.2f} $")
    typer.echo(f"plafond configure      {settings.budget_usd:.2f} $")
    typer.echo(
        "\nLes jetons d'entree sont estimes a 3,2 caracteres par jeton, volontairement\n"
        "pessimiste. Les chiffres publies viendront de `usage`, apres le premier run."
    )


@agents_app.command("calibrate")
def agents_calibrate(
    limit: int = typer.Option(0, help="Nombre d'incidents (0 = les 45)"),
    k: int = typer.Option(5, help="Fiches candidates servies a l'agent Historique"),
    effort: str = typer.Option("low"),
    model: str = typer.Option("", help="Par defaut : COUNCIL_MODEL"),
    budget: float = typer.Option(0.0, help="Plafond en dollars (0 = COUNCIL_BUDGET_USD)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Pour mesurer la variance"),
) -> None:
    """Mesure chaque specialiste SEUL. Premier appel facture du projet."""
    settings = load_settings()
    chosen = model or settings.model
    guard = BudgetGuard(limit_usd=budget or settings.budget_usd)
    client = AnthropicClient(
        model=chosen,
        budget=guard,
        cache_dir=CACHE_DIR / "llm",
        cache_enabled=settings.cache_enabled and not no_cache,
    )
    dataset = load_dataset()
    specialists = build_specialists(CaseRetriever(load_kb().entries), k)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    try:
        records = run_calibration(dataset, specialists, client, effort, limit or None)
    except BudgetExceeded as exc:
        typer.echo(f"ARRET : {exc}")
        raise typer.Exit(code=2) from exc

    out_dir = RESULTS_DIR / "raw" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "specialists.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")

    reports = summarize(records)
    markdown = render_markdown(reports, records, model=chosen, effort=effort, k=k, run_id=run_id)
    (PROJECT_ROOT / "docs" / "calibration.md").write_text(markdown, encoding="utf-8")
    typer.echo(markdown)
    typer.echo(f"traces brutes : {out_dir / 'specialists.jsonl'}")
    typer.echo(f"depense reelle : {guard.spent_usd:.4f} $ sur {guard.limit_usd:.2f} $")

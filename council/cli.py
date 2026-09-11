"""Ligne de commande du projet."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from council.agents.app import AppSpecialist
from council.agents.arbiter import Arbiter
from council.agents.base import BaseSpecialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.benchmark.calibration import dry_run, run_calibration, summarize
from council.benchmark.plots import accuracy_by_category, consensus_vs_accuracy
from council.benchmark.report import render_benchmark_markdown, render_markdown
from council.benchmark.runner import BenchmarkRunner, estimate_benchmark, read_results
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
from council.orchestration.graph import build_graph, investigate
from council.orchestration.trace import Tracer, read_trace, render_reasoning

app = typer.Typer(help="multi-agent-rca", no_args_is_help=True)
dataset_app = typer.Typer(help="Jeu de donnees synthetique", no_args_is_help=True)
agents_app = typer.Typer(help="Les trois specialistes", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")
benchmark_app = typer.Typer(help="Les quatre bras", no_args_is_help=True)
app.add_typer(agents_app, name="agents")
app.add_typer(benchmark_app, name="benchmark")


def build_specialists(retriever: CaseRetriever, k: int) -> list[BaseSpecialist]:
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


@app.command("investigate")
def investigate_cmd(
    incident_id: str = typer.Argument(..., help="Par exemple INC-001"),
    k: int = typer.Option(5),
    effort_specialist: str = typer.Option("low"),
    effort_arbiter: str = typer.Option("high"),
    model: str = typer.Option(""),
    budget: float = typer.Option(0.0),
    max_rounds: int = typer.Option(2),
) -> None:
    """Fait tourner le graphe complet sur un incident et ecrit sa trace."""
    settings = load_settings()
    chosen = model or settings.model
    guard = BudgetGuard(limit_usd=budget or settings.budget_usd)
    client = AnthropicClient(
        model=chosen,
        budget=guard,
        cache_dir=CACHE_DIR / "llm",
        cache_enabled=settings.cache_enabled,
    )
    dataset = load_dataset()
    incident = next((i for i in dataset.incidents if i.id == incident_id), None)
    if incident is None:
        typer.echo(f"incident {incident_id} inconnu")
        raise typer.Exit(code=1)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trace_path = RESULTS_DIR / "raw" / run_id / "trace.jsonl"
    tracer = Tracer(run_id=run_id, path=trace_path)
    graph = build_graph(
        specialists=build_specialists(CaseRetriever(load_kb().entries), k),
        arbiter=Arbiter(effort=effort_arbiter),
        client=client,
        tracer=tracer,
        effort_specialist=effort_specialist,
        max_rounds=max_rounds,
    )
    try:
        verdict = investigate(graph, incident)
    except BudgetExceeded as exc:
        typer.echo(f"ARRET : {exc}")
        raise typer.Exit(code=2) from exc

    typer.echo(render_reasoning(tracer.records, incident.id))
    typer.echo(f"cause retenue    : {verdict.cause or 'PAS DE CONSENSUS'}")
    typer.echo(f"confiance        : {verdict.confidence:.2f}  ({verdict.consensus})")
    typer.echo(f"allers-retours   : {verdict.rounds}")
    typer.echo(f"appels LLM       : {verdict.llm_calls}")
    typer.echo(f"jetons           : {verdict.input_tokens} entree / {verdict.output_tokens} sortie")
    typer.echo(f"cout             : {verdict.usd:.4f} $")
    typer.echo(f"revue humaine    : {'recommandee' if verdict.recommend_human_review else 'non'}")
    typer.echo(f"trace            : {trace_path}")


@app.command("replay")
def replay_cmd(
    run_id: str = typer.Argument(...),
    incident_id: str = typer.Option("", help="Vide = tous les incidents du run"),
) -> None:
    """Reconstitue le raisonnement depuis la trace. Aucun appel, aucun cout."""
    path = RESULTS_DIR / "raw" / run_id / "trace.jsonl"
    if not path.exists():
        typer.echo(f"trace introuvable : {path}")
        raise typer.Exit(code=1)
    records = read_trace(path)
    ids = [incident_id] if incident_id else sorted({r["incident_id"] for r in records})
    for current in ids:
        typer.echo(render_reasoning(records, current))


@benchmark_app.command("run")
def benchmark_run(
    limit: int = typer.Option(0, help="Nombre d'incidents (0 = les 45)"),
    passes: int = typer.Option(1, help="Passes successives, pour mesurer la variance"),
    k: int = typer.Option(5),
    efforts: str = typer.Option("medium,high", help="Niveaux d'effort de la baseline"),
    effort_specialist: str = typer.Option("low"),
    effort_arbiter: str = typer.Option("high"),
    model: str = typer.Option(""),
    budget: float = typer.Option(0.0),
    max_rounds: int = typer.Option(2),
    no_cache: bool = typer.Option(False, "--no-cache", help="Obligatoire au-dela d'une passe"),
) -> None:
    """Fait tourner les quatre bras sur les memes incidents."""
    settings = load_settings()
    chosen = model or settings.model
    if passes > 1 and not no_cache:
        typer.echo(
            "Refus : mesurer la variance avec le cache actif renverrait les memes\n"
            "reponses a chaque passe. Ajouter --no-cache."
        )
        raise typer.Exit(code=1)

    guard = BudgetGuard(limit_usd=budget or settings.budget_usd)
    client = AnthropicClient(
        model=chosen,
        budget=guard,
        cache_dir=CACHE_DIR / "llm",
        cache_enabled=settings.cache_enabled and not no_cache,
    )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / "raw" / run_id
    retriever = CaseRetriever(load_kb().entries)
    runner = BenchmarkRunner(
        dataset=load_dataset(),
        retriever=retriever,
        specialists=build_specialists(retriever, k),
        client=client,
        run_id=run_id,
        out_dir=out_dir,
        effort_specialist=effort_specialist,
        effort_arbiter=effort_arbiter,
        baseline_efforts=[e.strip() for e in efforts.split(",") if e.strip()],
        k=k,
        max_rounds=max_rounds,
    )
    results = runner.run(passes=passes, limit=limit or None)
    if runner.partial:
        typer.echo(f"BUDGET EPUISE : rapport partiel sur {len(results)} lignes.")

    _write_benchmark_outputs(results, run_id, chosen, passes, runner.partial)
    typer.echo(f"depense reelle : {guard.spent_usd:.4f} $ sur {guard.limit_usd:.2f} $")


@benchmark_app.command("report")
def benchmark_report(
    run_id: str = typer.Argument(...),
    model: str = typer.Option(""),
    passes: int = typer.Option(1),
) -> None:
    """Regenere le rapport depuis les traces brutes. Aucun appel, aucun cout."""
    path = RESULTS_DIR / "raw" / run_id / "arms.jsonl"
    if not path.exists():
        typer.echo(f"resultats introuvables : {path}")
        raise typer.Exit(code=1)
    results = read_results(path)
    _write_benchmark_outputs(results, run_id, model or load_settings().model, passes, False)


def _write_benchmark_outputs(
    results: list[Any], run_id: str, model: str, passes: int, partial: bool
) -> None:
    markdown = render_benchmark_markdown(
        results, run_id=run_id, model=model, passes=passes, partial=partial
    )
    (PROJECT_ROOT / "docs" / "benchmark.md").write_text(markdown, encoding="utf-8")
    figure_1 = accuracy_by_category(results, RESULTS_DIR / "accuracy_by_category.png")
    figure_2 = consensus_vs_accuracy(results, RESULTS_DIR / "consensus_vs_accuracy.png")
    typer.echo(markdown)
    typer.echo(f"rapport   : {PROJECT_ROOT / 'docs' / 'benchmark.md'}")
    typer.echo(f"graphiques: {figure_1}, {figure_2}")


@benchmark_app.command("dry-run")
def benchmark_dry_run(
    k: int = typer.Option(5),
    efforts: str = typer.Option("medium,high"),
    max_rounds: int = typer.Option(2),
    model: str = typer.Option(""),
) -> None:
    """Encadre le cout d'un run complet. Aucun reseau, aucun cout."""
    import tempfile

    from council.budget import cost_usd

    settings = load_settings()
    chosen = model or settings.model
    retriever = CaseRetriever(load_kb().entries)
    with tempfile.TemporaryDirectory() as tmp:
        estimates = estimate_benchmark(
            load_dataset(),
            retriever,
            build_specialists(retriever, k),
            out_dir=Path(tmp),
            baseline_efforts=[e.strip() for e in efforts.split(",") if e.strip()],
            k=k,
            max_rounds=max_rounds,
        )
    typer.echo(f"modele {chosen} — 45 incidents, 4 bras\n")
    for label, (calls, tokens_in, tokens_out) in estimates.items():
        typer.echo(
            f"  {label:<28} {calls:>4} appels  "
            f"{tokens_in:>8,} jetons in  {tokens_out:>7,} out  "
            f"{cost_usd(chosen, tokens_in, tokens_out):>6.2f} $"
        )
    typer.echo(f"\nplafond configure : {settings.budget_usd:.2f} $")
    typer.echo(
        "Le nombre de relances depend des reponses : le run reel tombera entre ces\n"
        "deux bornes. Les jetons d'entree sont estimes a 3,2 caracteres par jeton."
    )

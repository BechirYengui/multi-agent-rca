"""Commandes `council benchmark` : chiffrer, faire tourner, regenerer le rapport."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import typer

from council.benchmark.estimate import estimate_benchmark
from council.benchmark.plots import accuracy_by_category, consensus_vs_accuracy
from council.benchmark.report_benchmark import render_benchmark
from council.benchmark.runner import BenchmarkRunner, read_results
from council.cli.context import (
    build_specialists,
    load_dataset,
    load_retriever,
    make_client,
    new_run_id,
)
from council.config import PROJECT_ROOT, RESULTS_DIR, load_settings

benchmark_app = typer.Typer(help="Les quatre bras", no_args_is_help=True)


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

    client, guard, _ = make_client(model, budget, no_cache=no_cache)
    run_id = new_run_id()
    out_dir = RESULTS_DIR / "raw" / run_id
    retriever = load_retriever()
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
    markdown = render_benchmark(results, run_id=run_id, model=model, passes=passes, partial=partial)
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

    settings = load_settings()
    chosen = model or settings.model
    retriever = load_retriever()
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
    for label, estimate in estimates.items():
        typer.echo(
            f"  {label:<28} {estimate.calls:>4} appels  "
            f"{estimate.input_tokens:>8,} jetons in  {estimate.output_tokens:>7,} out  "
            f"{estimate.usd(chosen):>6.2f} $"
        )
    typer.echo(f"\nplafond configure : {settings.budget_usd:.2f} $")
    typer.echo(
        "Le nombre de relances depend des reponses : le run reel tombera entre ces\n"
        "deux bornes. Les jetons d'entree sont estimes a 3,2 caracteres par jeton."
    )

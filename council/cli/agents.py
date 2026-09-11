"""Commandes `council agents` : chiffrer puis mesurer les specialistes seuls."""

from __future__ import annotations

import json

import typer

from council.benchmark.calibration import run_calibration, summarize
from council.benchmark.estimate import estimate_calibration
from council.benchmark.report_calibration import render_calibration
from council.budget import BudgetExceeded
from council.cli.context import (
    build_specialists,
    load_dataset,
    load_retriever,
    make_client,
    new_run_id,
)
from council.config import PROJECT_ROOT, RESULTS_DIR, load_settings

agents_app = typer.Typer(help="Les trois specialistes", no_args_is_help=True)


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
    specialists = build_specialists(load_retriever(), k)
    estimate = estimate_calibration(dataset, specialists, effort)

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
    client, guard, _ = make_client(model, budget, no_cache=no_cache)
    dataset = load_dataset()
    specialists = build_specialists(load_retriever(), k)
    run_id = new_run_id()

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
    markdown = render_calibration(reports, records, model=chosen, effort=effort, k=k, run_id=run_id)
    (PROJECT_ROOT / "docs" / "calibration.md").write_text(markdown, encoding="utf-8")
    typer.echo(markdown)
    typer.echo(f"traces brutes : {out_dir / 'specialists.jsonl'}")
    typer.echo(f"depense reelle : {guard.spent_usd:.4f} $ sur {guard.limit_usd:.2f} $")

"""Commandes `council investigate` et `council replay` : un incident, sa trace."""

from __future__ import annotations

import typer

from council.agents.arbiter import Arbiter
from council.budget import BudgetExceeded
from council.cli.context import (
    build_specialists,
    load_dataset,
    load_retriever,
    make_client,
    new_run_id,
)
from council.config import RESULTS_DIR
from council.orchestration.graph import build_graph, investigate
from council.orchestration.trace import Tracer, read_trace, render_reasoning


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
    client, guard, _ = make_client(model, budget)
    dataset = load_dataset()
    incident = next((i for i in dataset.incidents if i.id == incident_id), None)
    if incident is None:
        typer.echo(f"incident {incident_id} inconnu")
        raise typer.Exit(code=1)

    run_id = new_run_id()
    trace_path = RESULTS_DIR / "raw" / run_id / "trace.jsonl"
    tracer = Tracer(run_id=run_id, path=trace_path)
    graph = build_graph(
        specialists=build_specialists(load_retriever(), k),
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
    typer.echo(f"budget restant   : {guard.remaining_usd:.2f} $ sur {guard.limit_usd:.2f} $")
    typer.echo(f"revue humaine    : {'recommandee' if verdict.recommend_human_review else 'non'}")
    typer.echo(f"trace            : {trace_path}")


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

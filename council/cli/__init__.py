"""Ligne de commande. Ce module n'assemble que les sous-applications.

Une commande par fichier : `dataset`, `agents`, `benchmark`, plus `investigate`
et `replay` qui portent sur un incident unique.
"""

from __future__ import annotations

import typer

from council.cli.agents import agents_app
from council.cli.bench import benchmark_app
from council.cli.dataset import dataset_app
from council.cli.investigate import investigate_cmd, replay_cmd

app = typer.Typer(help="multi-agent-rca", no_args_is_help=True)
app.add_typer(dataset_app, name="dataset")
app.add_typer(agents_app, name="agents")
app.add_typer(benchmark_app, name="benchmark")
app.command("investigate")(investigate_cmd)
app.command("replay")(replay_cmd)

__all__ = ["app"]


if __name__ == "__main__":  # pragma: no cover
    app()

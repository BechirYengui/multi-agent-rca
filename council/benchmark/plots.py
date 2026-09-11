"""Deux graphiques, pas douze.

Le premier montre ou le gain se joue (par categorie), le second montre si
l'accord des agents est un signal. Tout le reste est dans les tableaux : un
graphique qui ne repond pas a une question precise est une decoration.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # aucun affichage : le poste n'a pas de serveur graphique garanti
import matplotlib.pyplot as plt

from council.benchmark.formatting import CATEGORY_LABEL
from council.benchmark.metrics import consensus_analysis, summarize
from council.benchmark.runner import ArmResult
from council.data.taxonomy import Category

ARM_ORDER = ("floor", "vote", "council")


def accuracy_by_category(results: list[ArmResult], path: Path) -> Path:
    summaries = summarize(results, pass_index=1)
    arms = [a for a in ARM_ORDER if a in summaries]
    arms += sorted(a for a in summaries if a.startswith("baseline"))
    categories = [c.value for c in Category]

    width = 0.8 / max(1, len(arms))
    figure, axes = plt.subplots(figsize=(9, 5))
    for index, arm in enumerate(arms):
        values = [(summaries[arm].category_accuracy(c) or 0.0) * 100 for c in categories]
        offsets = [i + index * width - 0.4 + width / 2 for i in range(len(categories))]
        axes.bar(offsets, values, width=width, label=arm)

    axes.set_xticks(range(len(categories)))
    axes.set_xticklabels([CATEGORY_LABEL[c] for c in categories])
    axes.set_ylabel("taux de reussite (%)")
    axes.set_ylim(0, 105)
    axes.axhline(25, linestyle=":", linewidth=1, color="grey")
    axes.annotate("hasard (25 %)", xy=(-0.45, 27), fontsize=8, color="grey")
    axes.set_title("Taux de reussite par categorie d'incident")
    axes.legend(frameon=False, ncol=len(arms), fontsize=8)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def consensus_vs_accuracy(results: list[ArmResult], path: Path) -> Path:
    analysis = consensus_analysis(results)
    kinds = sorted(analysis.by_kind, key=lambda k: -analysis.by_kind[k][1])
    accuracies = [analysis.by_kind[k][0] / analysis.by_kind[k][1] * 100 for k in kinds]
    counts = [analysis.by_kind[k][1] for k in kinds]

    figure, axes = plt.subplots(figsize=(8, 4.5))
    bars = axes.bar(range(len(kinds)), accuracies, color="#3b6ea5")
    for bar, count in zip(bars, counts, strict=True):
        axes.annotate(
            f"n={count}",
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2),
            ha="center",
            fontsize=8,
        )
    axes.set_xticks(range(len(kinds)))
    axes.set_xticklabels(kinds, rotation=15)
    axes.set_ylabel("taux de reussite (%)")
    axes.set_ylim(0, 110)
    axes.set_title(f"L'accord des agents predit-il l'exactitude ?  (phi = {analysis.phi:+.3f})")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path

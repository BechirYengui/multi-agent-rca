"""Petits helpers de mise en forme partages par les deux rapports."""

from __future__ import annotations

from council.data.taxonomy import Category

CATEGORY_LABEL: dict[str, str] = {
    Category.INFRA_PURE.value: "infra pure",
    Category.APP_PURE.value: "appli pure",
    Category.HISTORY_REQUIRED.value: "historique",
    Category.AMBIGUOUS.value: "ambigu",
}


def pct(value: float) -> str:
    return f"{value:.1%}"


def category_header() -> list[str]:
    """En-tete de tableau commun : une colonne par categorie d'incident."""
    return [
        "| Bras | " + " | ".join(CATEGORY_LABEL[c.value] for c in Category) + " |",
        "|---|" + "---|" * len(Category),
    ]

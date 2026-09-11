"""Mise en forme des mesures de calibration."""

from __future__ import annotations

from council.benchmark.calibration import AgentReport, SpecialistRecord
from council.data.taxonomy import Category

CATEGORY_LABEL = {
    Category.INFRA_PURE.value: "infra pure",
    Category.APP_PURE.value: "appli pure",
    Category.HISTORY_REQUIRED.value: "historique",
    Category.AMBIGUOUS.value: "ambigu",
}


def _pct(value: float) -> str:
    return f"{value:.1%}"


def render_markdown(
    reports: dict[str, AgentReport],
    records: list[SpecialistRecord],
    *,
    model: str,
    effort: str,
    k: int,
    run_id: str,
) -> str:
    agents = sorted(reports)
    total_usd = sum(report.usd for report in reports.values())
    cached = sum(int(record.from_cache) for record in records)

    lines: list[str] = [
        "# Calibration des trois specialistes",
        "",
        f"Run `{run_id}` — modele `{model}`, effort `{effort}`, "
        f"{k} fiches candidates pour l'agent Historique.",
        f"{len(records)} appels, dont {cached} servis par le cache. Cout : {total_usd:.4f} $.",
        "",
        "## 1. Taux de reussite de chaque agent, seul",
        "",
        "| Agent | Reussite (IC 95 %) | Reussite hors abstention | Verite dans le top 3 | "
        "Abstentions | Brier |",
        "|---|---|---|---|---|---|",
    ]
    for agent in agents:
        report = reports[agent]
        low, high = report.interval
        lines.append(
            f"| `{agent}` | {_pct(report.accuracy)} "
            f"({_pct(low)}–{_pct(high)}) | {_pct(report.accuracy_when_answering)} | "
            f"{_pct(report.top3 / report.n if report.n else 0)} | "
            f"{_pct(report.abstention_rate)} | {report.brier:.3f} |"
        )

    lines += [
        "",
        "## 2. Par categorie d'incident",
        "",
        "| Agent | " + " | ".join(CATEGORY_LABEL[c.value] for c in Category) + " |",
        "|---|" + "---|" * len(Category),
    ]
    for agent in agents:
        report = reports[agent]
        cells = []
        for category in Category:
            pair = report.by_category.get(category.value)
            cells.append(f"{pair[0]}/{pair[1]}" if pair else "—")
        lines.append(f"| `{agent}` | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 3. La confiance annoncee porte-t-elle une information ?",
        "",
        "Ecart = confiance moyenne annoncee moins exactitude reelle. Positif = sur-confiance.",
        "",
        "| Agent | Tranche | n | Confiance moyenne | Exactitude | Ecart |",
        "|---|---|---|---|---|---|",
    ]
    for agent in agents:
        for bucket in reports[agent].bins:
            if bucket.count == 0:
                continue
            lines.append(
                f"| `{agent}` | {bucket.low:.1f}–{bucket.high:.1f} | {bucket.count} | "
                f"{bucket.mean_confidence:.2f} | {_pct(bucket.accuracy)} | "
                f"{bucket.gap:+.2f} |"
            )

    lines += ["", "### Verdict sur le routage de l'arbitre", ""]
    flat = [agent for agent in agents if reports[agent].confidence_is_flat]
    if flat:
        lines += [
            f"**La confiance est plate pour {', '.join('`' + a + '`' for a in flat)}** : "
            f"plus de 80 % des reponses depassent 0,80. Le repli prevu au plan "
            f"s'applique — faire deriver la confiance du nombre de preuves citees "
            f"plutot que d'une auto-evaluation, puis re-mesurer avant d'ecrire "
            f"l'arbitre.",
        ]
    else:
        lines += [
            "La confiance discrimine : aucun agent ne depasse 0,80 sur plus de 80 % "
            "des cas. L'arbitre peut router dessus.",
        ]
    return "\n".join(lines) + "\n"

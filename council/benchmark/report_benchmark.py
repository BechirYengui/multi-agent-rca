"""Rapport de benchmark : les quatre bras, et ce qu'ils disent.

Le rapport calcule lui-meme sa phrase de tete, y compris dans les deux
formulations ou la baseline gagne ou fait jeu egal. Aucune des trois n'est
choisie apres coup : elles existent toutes les trois avant le premier run.
"""

from __future__ import annotations

from council.benchmark.formatting import CATEGORY_LABEL, category_header, pct
from council.benchmark.metrics import (
    ArmSummary,
    abstention_by_category,
    accuracy_per_pass,
    best_baseline,
    consensus_analysis,
    paired,
    summarize,
)
from council.benchmark.runner import ArmResult
from council.data.taxonomy import Category


def _headline(council: ArmSummary, baseline: ArmSummary, floor: ArmSummary) -> str:
    """La premiere phrase du rapport, calculee -- pas redigee a l'avance.

    Elle dit ce que les chiffres disent, y compris quand ils sont defavorables au
    systeme multi-agents. Les trois formulations existent avant le premier run.
    """
    delta = council.accuracy - baseline.accuracy
    ratio = (council.usd / baseline.usd) if baseline.usd > 0 else 0.0
    cost = f"{ratio:.1f} fois le cout" if ratio > 0 else "un cout non mesure (client simule)"
    cheaper = f"{ratio:.1f} fois moins cher" if ratio > 0 else "moins cher"
    common = (
        f"Sur {council.n} incidents synthetiques, le conseil d'agents identifie la bonne "
        f"cause dans {council.accuracy:.1%} des cas contre {baseline.accuracy:.1%} pour un "
        f"agent unique recevant le meme contexte"
    )
    if delta > 0:
        return f"**{common}, pour {cost}** (plancher deterministe : {floor.accuracy:.1%})."
    if abs(delta) < 1e-9:
        return (
            f"**{common} — soit exactement le meme resultat, pour {cost}** "
            f"(plancher deterministe : {floor.accuracy:.1%})."
        )
    return (
        f"**{common} : l'agent unique fait MIEUX de {abs(delta):.1%}, et coute "
        f"{cheaper}** (plancher deterministe : {floor.accuracy:.1%})."
    )


def render_benchmark(
    results: list[ArmResult],
    *,
    run_id: str,
    model: str,
    passes: int,
    partial: bool = False,
) -> str:
    summaries = summarize(results, pass_index=1)
    baseline_arm = best_baseline(summaries)
    council = summaries.get("council")
    floor = summaries.get("floor")
    baseline = summaries.get(baseline_arm) if baseline_arm else None
    vote = summaries.get("vote")

    lines: list[str] = ["# Benchmark — quatre bras sur les memes incidents", ""]
    if partial:
        lines += [
            "> **RAPPORT PARTIEL — budget epuise avant la fin du run.** Les chiffres "
            "portent sur les incidents effectivement traites.",
            "",
        ]
    if council and baseline and floor:
        lines += [_headline(council, baseline, floor), ""]

    lines += [
        f"Run `{run_id}` — modele `{model}`, {passes} passe(s). "
        f"Baseline retenue : `{baseline_arm}` (son MEILLEUR niveau d'effort).",
        "",
        "## 1. Les quatre bras",
        "",
        "| Bras | Reussite (IC 95 %) | Appels/inc. | Cout total | Latence med. | Abstentions |",
        "|---|---|---|---|---|---|",
    ]
    for arm in sorted(summaries):
        summary = summaries[arm]
        low, high = summary.interval
        lines.append(
            f"| `{arm}` | {pct(summary.accuracy)} ({pct(low)}–{pct(high)}) | "
            f"{summary.calls_per_incident:.1f} | {summary.usd:.3f} $ | "
            f"{summary.median_latency_ms:.0f} ms | {pct(summary.abstentions / summary.n)} |"
        )

    lines += [
        "",
        "L'intervalle de Wilson vaut environ ±13 points a n=45 : lu seul, ce tableau ne "
        "permet de conclure a rien. C'est le test apparie de la section 3 qui tranche.",
        "",
        "## 2. Par categorie d'incident",
        "",
        *category_header(),
    ]
    for arm in sorted(summaries):
        cells = []
        for category in Category:
            value = summaries[arm].category_accuracy(category.value)
            cells.append(pct(value) if value is not None else "—")
        lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Rappel de `docs/dataset.md` : le plancher deterministe atteint deja 100 % sur "
        "l'infra pure. Aucun gain du multi-agents ne peut venir de cette colonne.",
        "",
        "## 3. Comparaisons appariees (McNemar exact, passe 1)",
        "",
        "| Comparaison | A seul | B seul | p | Verdict |",
        "|---|---|---|---|---|",
    ]
    comparisons = []
    if baseline_arm:
        comparisons.append(("council", baseline_arm))
        comparisons.append((baseline_arm, "floor"))
    comparisons.append(("council", "vote"))
    for arm_a, arm_b in comparisons:
        if arm_a not in summaries or arm_b not in summaries:
            continue
        comparison = paired(results, arm_a, arm_b)
        lines.append(
            f"| `{arm_a}` vs `{arm_b}` | {comparison.only_a} | {comparison.only_b} | "
            f"{comparison.p_value:.3f} | {comparison.verdict} |"
        )

    if council and vote:
        lines += [
            "",
            "La ligne `council` vs `vote` est celle qui juge l'arbitre : `vote` rejoue les "
            "memes trois hypotheses en prenant simplement la plus confiante, sans aucun "
            "appel supplementaire. Si l'arbitre ne la bat pas, il ne paie pas son cout.",
        ]

    analysis = consensus_analysis(results)
    lines += [
        "",
        "## 4. L'accord des trois agents est-il un signal ?",
        "",
        "| Forme de l'accord | Justes / total |",
        "|---|---|",
    ]
    for kind, (hits, total) in sorted(analysis.by_kind.items()):
        lines.append(f"| `{kind}` | {hits}/{total} ({pct(hits / total)}) |")
    lines += [
        "",
        f"Unanimite : {pct(analysis.unanimous_accuracy)} de reussite "
        f"({analysis.unanimous_correct}/{analysis.unanimous_total}). "
        f"Reste : {pct(analysis.other_accuracy)} "
        f"({analysis.other_correct}/{analysis.other_total}). "
        f"Coefficient phi = {analysis.phi:+.3f}.",
        "",
    ]
    if analysis.convergence_predicts_correctness:
        lines.append(
            "La convergence predit bien l'exactitude : les cas ou les trois agents "
            "tombent d'accord sont plus souvent justes. C'est la these du projet, et "
            "elle tient sur ce jeu de donnees."
        )
    else:
        lines.append(
            "**La convergence ne predit PAS l'exactitude sur ce jeu de donnees.** Les cas "
            "d'accord ne sont pas plus souvent justes que les autres. La these centrale du "
            "projet ne tient pas ici : les trois agents tournant sur le meme modele, leurs "
            "erreurs sont correlees, et leur accord ne constitue pas une confirmation "
            "independante."
        )

    abstentions = abstention_by_category(results)
    lines += [
        "",
        "## 5. Comportement sur les cas ambigus",
        "",
        "Sur un incident volontairement ambigu, la bonne reponse n'est pas de trouver la "
        "cause : c'est de ne pas etre confiant. Taux d'absence de consensus du bras "
        "`council` :",
        "",
        "| Categorie | Sans consensus |",
        "|---|---|",
    ]
    for category in Category:
        rate = abstentions.get(category.value)
        lines.append(
            f"| {CATEGORY_LABEL[category.value]} | {pct(rate) if rate is not None else '—'} |"
        )
    ambiguous_rate = abstentions.get(Category.AMBIGUOUS.value, 0.0)
    others = [v for k, v in abstentions.items() if k != Category.AMBIGUOUS.value]
    mean_other = sum(others) / len(others) if others else 0.0
    lines += [
        "",
        (
            f"Le systeme s'abstient {pct(ambiguous_rate)} du temps sur les cas ambigus "
            f"contre {pct(mean_other)} ailleurs : il distingue donc les situations ou il "
            f"ne faut pas trancher."
            if ambiguous_rate > mean_other
            else f"**Le systeme ne s'abstient pas davantage sur les cas ambigus "
            f"({pct(ambiguous_rate)}) qu'ailleurs ({pct(mean_other)}).** Il tranche avec "
            f"la meme assurance sur des incidents construits pour ne pas etre tranchables, "
            f"ce qui est un defaut et non une performance."
        ),
    ]

    if passes > 1:
        lines += [
            "",
            "## 6. Variance entre passes",
            "",
            "`temperature` n'existe plus sur ces modeles : la variance ne se supprime pas, "
            "elle se mesure. Passes executees avec le cache desactive.",
            "",
            "| Bras | " + " | ".join(f"passe {i}" for i in range(1, passes + 1)) + " |",
            "|---|" + "---|" * passes,
        ]
        for arm in sorted(summaries):
            per_pass = accuracy_per_pass(results, arm)
            cells = [pct(per_pass.get(i, 0.0)) for i in range(1, passes + 1)]
            lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 7. Ce que ce benchmark ne dit pas",
        "",
        "- Le jeu de donnees est synthetique : une seule cause par incident, pas de bruit "
        "de production, fenetre temporelle deja cadree (`docs/dataset.md` §8). Les taux "
        "ci-dessus comparent des **architectures entre elles a information constante** ; "
        "ils ne sont pas transposables a une production reelle.",
        "- Les trois specialistes tournent sur le meme modele. Leur accord n'est pas "
        "l'accord de trois experts independants.",
        "- n = 45. Seul le test apparie de la section 3 a la puissance de conclure.",
        "",
        f"Chaque chiffre est recalculable depuis `results/raw/{run_id}/arms.jsonl`.",
    ]
    return "\n".join(lines) + "\n"

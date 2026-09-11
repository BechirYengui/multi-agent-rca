"""Les mesures du rapport. Aucune n'est choisie apres avoir vu les resultats.

Trois d'entre elles peuvent facher, et c'est pour cela qu'elles sont ecrites
ici avant le premier run :

1. **La convergence predit-elle l'exactitude ?** Si les incidents ou les trois
   agents tombent d'accord ne sont pas plus souvent justes, la these centrale du
   projet tombe, et le rapport doit l'ecrire en tete.
2. **Par categorie.** Il est attendu que la baseline gagne sur l'infra pure : le
   plancher deterministe y est deja a 100 %, la decomposition ne peut qu'ajouter
   du bruit. Ce resultat ira dans le tableau, pas dans une note de bas de page.
3. **Comportement sur les cas ambigus.** Le bon comportement n'y est pas de
   trouver la cause, c'est de s'abstenir. Un systeme qui tranche avec assurance
   sur un cas ambigu est MOINS bon, et la mesure le compte ainsi.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from council.benchmark.runner import ArmResult
from council.benchmark.stats import mcnemar_exact, phi_coefficient, wilson_interval
from council.data.taxonomy import Category

# En dessous de ce nombre de paires discordantes, le test apparie ne tranche
# rien. Regle posee dans docs/plan.md AVANT toute execution, pour qu'aucun
# resultat non significatif ne soit presente comme une « tendance ».
MIN_DISCORDANT_PAIRS = 10


@dataclass
class ArmSummary:
    arm: str
    n: int = 0
    correct: int = 0
    abstentions: int = 0
    usd: float = 0.0
    llm_calls: int = 0
    latencies: list[float] = field(default_factory=list)
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.correct, self.n)

    @property
    def calls_per_incident(self) -> float:
        return self.llm_calls / self.n if self.n else 0.0

    @property
    def median_latency_ms(self) -> float:
        return median(self.latencies) if self.latencies else 0.0

    def category_accuracy(self, category: str) -> float | None:
        pair = self.by_category.get(category)
        return pair[0] / pair[1] if pair and pair[1] else None


def summarize(results: list[ArmResult], pass_index: int | None = None) -> dict[str, ArmSummary]:
    selected = [r for r in results if pass_index is None or r.pass_index == pass_index]
    summaries: dict[str, ArmSummary] = {}
    per_category: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for row in selected:
        summary = summaries.setdefault(row.arm, ArmSummary(arm=row.arm))
        summary.n += 1
        summary.correct += int(row.correct)
        summary.abstentions += int(row.predicted is None)
        summary.usd += row.usd
        summary.llm_calls += row.llm_calls
        summary.latencies.append(row.latency_ms)
        per_category[row.arm][row.category].append(int(row.correct))

    for arm, categories in per_category.items():
        summaries[arm].by_category = {
            category: (sum(values), len(values)) for category, values in categories.items()
        }
    return summaries


@dataclass(frozen=True)
class PairedComparison:
    arm_a: str
    arm_b: str
    only_a: int
    only_b: int
    both: int
    neither: int
    p_value: float

    @property
    def discordant(self) -> int:
        return self.only_a + self.only_b

    @property
    def conclusive(self) -> bool:
        return self.discordant >= MIN_DISCORDANT_PAIRS and self.p_value < 0.05

    @property
    def verdict(self) -> str:
        if self.discordant < MIN_DISCORDANT_PAIRS:
            # La regle du seuil a ete posee AVANT le premier run. On la respecte
            # meme quand la p-valeur est basse -- sinon ce ne serait plus une
            # regle, seulement un filtre applique aux resultats qui derangent.
            # La p-valeur est neanmoins affichee : on ne cache pas le chiffre,
            # on refuse seulement d'en tirer une conclusion.
            return (
                f"non concluant : {self.discordant} paires discordantes pour un seuil "
                f"de {MIN_DISCORDANT_PAIRS} fixe d'avance (p = {self.p_value:.3f})"
            )
        if self.p_value >= 0.05:
            return f"difference non significative (p = {self.p_value:.3f})"
        winner = self.arm_a if self.only_a > self.only_b else self.arm_b
        return f"{winner} l'emporte (p = {self.p_value:.3f})"


def paired(
    results: list[ArmResult], arm_a: str, arm_b: str, pass_index: int = 1
) -> PairedComparison:
    """Test apparie sur UNE passe.

    On ne fusionne pas les passes : deux passes du meme incident ne sont pas deux
    observations independantes, et les empiler gonflerait artificiellement la
    puissance du test. Les autres passes servent a mesurer la variance, pas a
    grossir l'echantillon.
    """
    by_incident: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in results:
        if row.pass_index == pass_index and row.arm in (arm_a, arm_b):
            by_incident[row.incident_id][row.arm] = row.correct

    only_a = only_b = both = neither = 0
    for outcomes in by_incident.values():
        if arm_a not in outcomes or arm_b not in outcomes:
            continue
        a, b = outcomes[arm_a], outcomes[arm_b]
        if a and b:
            both += 1
        elif a:
            only_a += 1
        elif b:
            only_b += 1
        else:
            neither += 1
    return PairedComparison(
        arm_a=arm_a,
        arm_b=arm_b,
        only_a=only_a,
        only_b=only_b,
        both=both,
        neither=neither,
        p_value=mcnemar_exact(only_a, only_b),
    )


@dataclass(frozen=True)
class ConsensusAnalysis:
    by_kind: dict[str, tuple[int, int]]
    unanimous_correct: int
    unanimous_total: int
    other_correct: int
    other_total: int
    phi: float

    @property
    def unanimous_accuracy(self) -> float:
        return self.unanimous_correct / self.unanimous_total if self.unanimous_total else 0.0

    @property
    def other_accuracy(self) -> float:
        return self.other_correct / self.other_total if self.other_total else 0.0

    @property
    def convergence_predicts_correctness(self) -> bool:
        return self.phi > 0.0 and self.unanimous_accuracy > self.other_accuracy


def consensus_analysis(results: list[ArmResult], pass_index: int = 1) -> ConsensusAnalysis:
    """La mesure centrale : l'accord des trois agents est-il un signal ?"""
    rows = [r for r in results if r.arm == "council" and r.pass_index == pass_index]
    by_kind: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_kind[row.consensus or "unknown"].append(int(row.correct))

    unanimous = [r for r in rows if r.consensus == "unanimous"]
    other = [r for r in rows if r.consensus != "unanimous"]
    a = sum(int(r.correct) for r in unanimous)
    b = len(unanimous) - a
    c = sum(int(r.correct) for r in other)
    d = len(other) - c
    return ConsensusAnalysis(
        by_kind={kind: (sum(values), len(values)) for kind, values in by_kind.items()},
        unanimous_correct=a,
        unanimous_total=len(unanimous),
        other_correct=c,
        other_total=len(other),
        phi=phi_coefficient(a, b, c, d),
    )


def abstention_by_category(
    results: list[ArmResult], arm: str = "council", pass_index: int = 1
) -> dict[str, float]:
    """S'abstenir est le bon comportement sur un cas ambigu, pas ailleurs."""
    counts: dict[str, list[int]] = defaultdict(list)
    for row in results:
        if row.arm == arm and row.pass_index == pass_index:
            counts[row.category].append(int(row.predicted is None))
    return {category: sum(values) / len(values) for category, values in counts.items() if values}


def best_baseline(summaries: dict[str, ArmSummary]) -> str:
    """Le rapport retient le MEILLEUR score de la baseline, pas le plus flatteur pour nous."""
    candidates = [arm for arm in summaries if arm.startswith("baseline")]
    if not candidates:
        return ""
    return max(candidates, key=lambda arm: summaries[arm].accuracy)


def accuracy_per_pass(results: list[ArmResult], arm: str) -> dict[int, float]:
    """Variance entre passes : ce que coute l'absence de `temperature`."""
    counts: dict[int, list[int]] = defaultdict(list)
    for row in results:
        if row.arm == arm:
            counts[row.pass_index].append(int(row.correct))
    return {index: sum(values) / len(values) for index, values in sorted(counts.items()) if values}


def category_labels() -> list[str]:
    return [category.value for category in Category]

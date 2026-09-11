"""Statistiques du benchmark, en bibliotheque standard.

Pourquoi pas scipy : ces quatre fonctions tiennent en cinquante lignes, se
verifient a la main sur des valeurs connues, et evitent une dependance de
30 Mo a un projet qui tourne sur un disque mecanique. Chacune a son test avec
une valeur de reference.

Le choix qui compte ici n'est pas l'outil, c'est le **test apparie**. Avec
n = 45, l'intervalle de confiance a 95 % d'un taux de 70 % vaut +/- 13 points :
comparer deux proportions independantes ne detecterait qu'un ecart superieur a
~20 points. Les quatre bras tournant sur les MEMES incidents, McNemar ne regarde
que les paires discordantes et devient nettement plus puissant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z_95 = 1.959963984540054


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Intervalle de Wilson : correct pour les petits effectifs, contrairement a Wald."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    half = (z / denominator) * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))
    return (max(0.0, centre - half), min(1.0, centre + half))


def _binomial_tail(k: int, n: int, *, upper: bool) -> float:
    """P(X >= k) si upper, sinon P(X <= k), pour X ~ Binomiale(n, 1/2)."""
    indices = range(k, n + 1) if upper else range(0, k + 1)
    total: int = sum(math.comb(n, i) for i in indices)
    # 2.0**n et non 2**n : mypy type `int ** int` comme Any (l'exposant peut
    # etre negatif), ce qui ferait remonter un Any jusqu'a la p-valeur.
    return total / 2.0**n


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Test exact de McNemar, bilateral.

    `only_a` : incidents ou le bras A a raison et B a tort. `only_b` : l'inverse.
    Les cas ou les deux ont raison (ou les deux tort) n'apportent rien et sont
    ignores -- c'est precisement ce qui rend le test apparie plus puissant.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = min(
        _binomial_tail(min(only_a, only_b), n, upper=False),
        _binomial_tail(max(only_a, only_b), n, upper=True),
    )
    return min(1.0, 2 * tail)


def phi_coefficient(a: int, b: int, c: int, d: int) -> float:
    """Correlation de deux variables binaires sur un tableau 2x2 [[a, b], [c, d]]."""
    denominator = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    if denominator == 0:
        return 0.0
    return (a * d - b * c) / denominator


def brier_score(pairs: list[tuple[float, bool]]) -> float:
    """Erreur quadratique moyenne entre confiance annoncee et resultat reel.

    0 = parfait. 0,25 = ce qu'obtient quelqu'un qui repond toujours 0,5.
    Un modele sur-confiant et souvent juste peut avoir un bon taux de reussite
    et un mauvais Brier : c'est exactement ce qu'on cherche a detecter, parce que
    l'arbitre route sur la confiance.
    """
    if not pairs:
        return 0.0
    return sum((confidence - float(correct)) ** 2 for confidence, correct in pairs) / len(pairs)


@dataclass(frozen=True)
class ReliabilityBin:
    low: float
    high: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Ecart confiance annoncee - exactitude reelle. Positif = sur-confiance."""
        return self.mean_confidence - self.accuracy


def reliability_bins(pairs: list[tuple[float, bool]], n_bins: int = 5) -> list[ReliabilityBin]:
    edges = [i / n_bins for i in range(n_bins + 1)]
    out: list[ReliabilityBin] = []
    for i in range(n_bins):
        low, high = edges[i], edges[i + 1]
        selected = [
            pair
            for pair in pairs
            if (low <= pair[0] < high) or (i == n_bins - 1 and pair[0] == 1.0)
        ]
        if not selected:
            out.append(ReliabilityBin(low, high, 0, 0.0, 0.0))
            continue
        out.append(
            ReliabilityBin(
                low=low,
                high=high,
                count=len(selected),
                mean_confidence=sum(c for c, _ in selected) / len(selected),
                accuracy=sum(int(ok) for _, ok in selected) / len(selected),
            )
        )
    return out

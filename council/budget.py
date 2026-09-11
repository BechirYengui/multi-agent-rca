"""Comptabilite des jetons et disjoncteur de depense.

Le plafond est verifie AVANT chaque appel, pas apres : un depassement doit
couter l'appel qu'on n'a pas fait, pas celui qu'on vient de payer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Tarifs releves le 2026-09-11 sur la documentation Anthropic, en dollars par
# million de jetons. Figes ici volontairement : un benchmark dont le cout se
# recalcule tout seul quand les tarifs bougent n'est plus reproductible.
PRICING_DATE = "2026-09-11"
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


class BudgetExceeded(RuntimeError):
    """Levee AVANT l'appel qui aurait fait depasser le plafond."""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    try:
        price_in, price_out = PRICING_USD_PER_MTOK[model]
    except KeyError as exc:  # pragma: no cover - garde-fou de configuration
        raise KeyError(
            f"Tarif inconnu pour {model!r}. Ajouter la ligne dans PRICING_USD_PER_MTOK "
            f"(releve du {PRICING_DATE}) plutot que de deviner."
        ) from exc
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_calls: int = 0
    usd: float = 0.0


@dataclass
class BudgetGuard:
    limit_usd: float
    usage: Usage = field(default_factory=Usage)

    @property
    def spent_usd(self) -> float:
        return self.usage.usd

    @property
    def remaining_usd(self) -> float:
        return self.limit_usd - self.usage.usd

    def check(self, projected_usd: float = 0.0) -> None:
        if self.usage.usd + projected_usd > self.limit_usd:
            raise BudgetExceeded(
                f"plafond {self.limit_usd:.2f} $ atteint "
                f"(depense {self.usage.usd:.4f} $, appel projete {projected_usd:.4f} $)"
            )

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        spent = cost_usd(model, input_tokens, output_tokens)
        self.usage.calls += 1
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.usd += spent
        return spent

    def record_cache_hit(self) -> None:
        self.usage.cached_calls += 1

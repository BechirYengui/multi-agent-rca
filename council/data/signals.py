"""Detection de signal dans une vue : « cette vue dit-elle quelque chose ? »

Module extrait de `audit.py` parce que deux clients tres differents en ont
besoin, et que faire dependre l'un de l'autre etait une inversion de couches :

- `data/audit.py` s'en sert pour VERIFIER que le generateur n'a pas laisse fuir
  un signal dans une vue qui devait rester muette ;
- `agents/keyword.py` s'en sert pour DIAGNOSTIQUER, comme le ferait une
  heuristique ecrite a la main.

Un agent qui importe depuis un module d'audit se lit mal et invite a melanger le
code qui mesure et le code qui est mesure. Les deux importent maintenant d'ici.
"""

from __future__ import annotations

from council.data.taxonomy import (
    FAMILY_TOKENS,
    NEUTRAL_BANDS,
    RPS_NEUTRAL_RATIO,
    SymptomFamily,
)
from council.models import LogWindow, MetricWindow
from council.text import token_set


def metric_signals(window: MetricWindow) -> set[str]:
    """Ce que la vue « metriques » porte comme signal discriminant.

    Retourne les noms des metriques hors bande neutre, plus `change_event` si la
    fenetre contient un deploiement ou une bascule de configuration.

    `error_rate` est exclue par construction : elle est elevee dans les 45
    incidents, c'est le symptome qui declenche l'alerte et non un indice sur la
    cause. La compter ici rendrait aucune vue jamais neutre, et le garde
    anti-fuite ne vaudrait plus rien.
    """
    signals: set[str] = set()
    for name, (low, high) in NEUTRAL_BANDS.items():
        values = [getattr(sample, name) for sample in window.samples]
        if low is not None and min(values) < low:
            signals.add(name)
        if high is not None and max(values) > high:
            signals.add(name)

    rps = [sample.rps for sample in window.samples]
    if min(rps) > 0 and max(rps) / min(rps) > RPS_NEUTRAL_RATIO:
        # La neutralite de `rps` est RELATIVE : un service a 200 requetes par
        # seconde et un autre a 4 000 sont tous deux normaux, seule la variation
        # dans la fenetre est un signal.
        signals.add("rps")

    if window.changes:
        signals.add("change_event")
    return signals


def log_families(window: LogWindow) -> set[SymptomFamily]:
    """Familles de symptomes dont le vocabulaire apparait dans les journaux.

    Le resultat est une famille, jamais une cause : le vocabulaire de surface
    est partage par les trois causes d'une meme famille. C'est exactement la
    limite qu'un lecteur de mots ne peut pas franchir.
    """
    tokens: set[str] = set()
    for line in window.lines:
        tokens |= token_set(line.message)
    for trace in window.traces:
        tokens |= token_set(trace.exception)
        for frame in trace.frames:
            tokens |= token_set(frame)
    return {family for family, family_tokens in FAMILY_TOKENS.items() if tokens & family_tokens}

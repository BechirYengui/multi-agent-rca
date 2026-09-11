"""Normalisation de texte partagee par le generateur, les gardes et le plancher.

Un seul tokeniseur pour tout le projet : si le garde anti-fuite et l'agent
mots-cles ne decoupaient pas le texte de la meme facon, le garde pourrait
declarer « aucune fuite » sur un texte que l'agent, lui, sait lire.
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    """Minuscules, accents retires, decoupe sur tout ce qui n'est pas alphanumerique."""
    return _WORD.findall(strip_accents(text).lower())


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def jaccard(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

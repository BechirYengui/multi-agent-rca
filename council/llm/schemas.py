"""Schemas JSON envoyes a l'API, derives de la taxonomie.

Ecrits a la main plutot que generes par `model_json_schema()` : Pydantic produit
des `$ref` vers `$defs` pour les enumerations, et une sortie structuree gagne a
etre un schema plat, explicite et relisible. Surtout, la liste fermee des causes
est ici derivee de `RootCause` : ajouter une cause a la taxonomie la fait
apparaitre dans le schema, sans edition manuelle et sans risque de divergence.
"""

from __future__ import annotations

from typing import Any

from council.data.taxonomy import LABEL_FR, RootCause

# Valeur autorisee en plus des 12 causes. Ce n'est PAS une cause : c'est
# l'aveu qu'il n'y a pas de quoi trancher.
ABSTENTION = "insufficient_evidence"


def cause_values() -> list[str]:
    return [cause.value for cause in RootCause] + [ABSTENTION]


def cause_catalogue() -> str:
    """La liste fermee, telle qu'elle est injectee dans les consignes."""
    lines = [f"- {cause.value} : {LABEL_FR[cause]}" for cause in RootCause]
    lines.append(f"- {ABSTENTION} : les donnees fournies ne permettent pas de trancher")
    return "\n".join(lines)


def specialist_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "cause": {
                    "type": "string",
                    "enum": cause_values(),
                    "description": "La cause racine retenue, ou insufficient_evidence.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": (
                        "Probabilite que la cause retenue soit la bonne. "
                        "0 si insufficient_evidence."
                    ),
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Observations chiffrees tirees UNIQUEMENT des donnees fournies."
                    ),
                },
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string", "enum": [c.value for c in RootCause]},
                    "description": "Au plus deux autres causes compatibles, par ordre decroissant.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Trois phrases au maximum.",
                },
            },
            "required": ["cause", "confidence", "evidence", "alternatives", "reasoning"],
            "additionalProperties": False,
        },
    }

"""Etat du graphe.

`hypotheses`, `clarifications` et `usages` portent un reducteur `operator.add` :
c'est ce qui rend le fan-in possible. Les trois specialistes ecrivent dans la
meme cle au meme super-pas ; sans reducteur, LangGraph refuserait l'ecriture
concurrente et il faudrait trois cles distinctes -- donc un noeud de collecte
qui les recolle a la main, et un routeur qui connait le nombre d'agents.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from council.models import CallUsage, Clarification, Hypothesis, Incident, Verdict


class InvestigationState(TypedDict, total=False):
    incident: Incident
    hypotheses: Annotated[list[Hypothesis], operator.add]
    clarifications: Annotated[list[Clarification], operator.add]
    usages: Annotated[list[CallUsage], operator.add]
    rounds: int
    route: str
    verdict: Verdict | None

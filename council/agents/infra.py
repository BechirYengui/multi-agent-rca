"""Agent Infrastructure : metriques systeme et changements recents, rien d'autre."""

from __future__ import annotations

from council.agents.base import build_system, call, render_user_message
from council.llm.client import LLMClient
from council.models import CallUsage, Hypothesis, Incident, SpecialistName

SYSTEM = build_system(
    role="Infrastructure",
    sees=(
        "des metriques systeme relevees toutes les 5 minutes sur une fenetre de "
        "60 minutes, et la liste des changements (deploiements, bascules de "
        "configuration) survenus juste avant l'incident. Le taux d'erreur est "
        "eleve dans tous les incidents qu'on te soumet : c'est le symptome qui a "
        "declenche l'alerte, pas un indice sur la cause."
    ),
)

INSTRUCTION = (
    "Voici les metriques de l'incident. Analyse leur evolution dans le temps, pas "
    "seulement leur valeur maximale."
)


class InfraSpecialist:
    name = SpecialistName.INFRA

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "low"
    ) -> tuple[Hypothesis, CallUsage]:
        user = render_user_message(incident.infra_view(), INSTRUCTION)
        return call(client, self.name, SYSTEM, user, effort, incident.id)

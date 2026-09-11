"""Agent Application : journaux et piles d'exception, rien d'autre."""

from __future__ import annotations

from council.agents.base import build_system, call, render_user_message
from council.llm.client import LLMClient
from council.models import CallUsage, Hypothesis, Incident, SpecialistName

SYSTEM = build_system(
    role="Application",
    sees=(
        "les lignes de journal applicatif et les piles d'exception relevees "
        "pendant la fenetre de l'incident. Certaines lignes sont du bruit "
        "d'exploitation normal ; a toi de faire le tri."
    ),
)

INSTRUCTION = (
    "Voici les journaux de l'incident. Regarde ou les exceptions sont levees, pas "
    "seulement ce qu'elles disent."
)


class AppSpecialist:
    name = SpecialistName.APP

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "low"
    ) -> tuple[Hypothesis, CallUsage]:
        user = render_user_message(incident.app_view(), INSTRUCTION)
        return call(client, self.name, SYSTEM, user, effort, incident.id)

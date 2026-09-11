"""Agent Application : journaux et piles d'exception, rien d'autre."""

from __future__ import annotations

from council.agents.base import BaseSpecialist, build_system, render_user_message
from council.models import Incident, SpecialistName

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


class AppSpecialist(BaseSpecialist):
    name = SpecialistName.APP
    system = SYSTEM

    def build_user(self, incident: Incident) -> str:
        return render_user_message(incident.app_view(), INSTRUCTION)

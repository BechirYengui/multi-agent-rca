"""Agent Historique : uniquement des incidents passes, selectionnes par similarite.

Le nombre de fiches candidates (`k`) est un parametre, pas une constante : la
mesure de la phase 1 donne un rappel de 63,6 % a k=3 et de 81,8 % a k=5. Servir
cinq candidats et laisser l'agent trancher coute quelques centaines de jetons et
evite de charger un modele d'embeddings de 800 Mo. C'est l'hypothese que la
phase 2 met a l'epreuve -- les deux valeurs sont mesurees, la meilleure est
retenue et l'autre est publiee.
"""

from __future__ import annotations

from council.agents.base import build_system, call, render_user_message
from council.agents.retrieval import CaseRetriever
from council.llm.client import LLMClient
from council.models import CallUsage, Hypothesis, Incident, SpecialistName

SYSTEM = build_system(
    role="Historique",
    sees=(
        "le symptome decrit par la supervision, et un extrait de la base des "
        "incidents deja resolus, selectionne automatiquement par similarite. "
        "Cette selection est imparfaite : la fiche qui explique reellement "
        "l'incident peut ne pas etre la premiere, et peut meme etre absente."
    ),
)

INSTRUCTION = (
    "Voici le symptome et les fiches d'incidents passes les plus proches. Retiens "
    "la cause d'une fiche uniquement si la FORME du symptome correspond (meme "
    "periodicite, meme condition de declenchement, meme perimetre touche) -- pas "
    "parce que les mots se ressemblent. Si aucune fiche ne correspond vraiment, "
    "abstiens-toi."
)


class HistorySpecialist:
    name = SpecialistName.HISTORY

    def __init__(self, retriever: CaseRetriever, k: int = 5) -> None:
        self.retriever = retriever
        self.k = k

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "low"
    ) -> tuple[Hypothesis, CallUsage]:
        query = incident.history_query()
        cases = self.retriever.search(query, k=self.k)
        view = {
            "incident_id": incident.id,
            "symptome": query,
            "fiches_candidates": [
                {
                    "id": case.entry.id,
                    "titre": case.entry.title,
                    "symptomes": case.entry.symptoms,
                    "diagnostic": case.entry.diagnosis,
                    "resolution": case.entry.resolution,
                    "cause_retenue": case.entry.root_cause.value,
                    "score_de_similarite": round(case.score, 3),
                }
                for case in cases
            ],
        }
        user = render_user_message(view, INSTRUCTION)
        return call(client, self.name, SYSTEM, user, effort, incident.id)

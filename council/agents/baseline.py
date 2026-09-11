"""Le bras temoin : un agent, un prompt, tout le contexte d'un coup.

L'equite envers la baseline est une exigence du protocole, ecrite avant de
connaitre les resultats :

- **meme modele, meme schema de sortie, meme taxonomie fermee** que les
  specialistes, et le meme droit de s'abstenir ;
- elle recoit **toute** l'information, y compris les fiches d'incidents passes
  retrouvees par similarite. Lui cacher une source aurait truque la comparaison
  en faveur du systeme multi-agents ;
- elle tourne a **deux niveaux d'effort** et le rapport retient son MEILLEUR
  score. Elle coute quelques dollars : lui donner sa meilleure chance est bon
  marche, et c'est la seule facon de rendre un eventuel ecart credible.

La seule chose qu'elle n'a pas, c'est la decomposition. C'est exactement la
variable qu'on teste.
"""

from __future__ import annotations

import json

from council.agents.base import build_system, parse_hypothesis
from council.agents.retrieval import CaseRetriever
from council.llm.client import LLMClient
from council.llm.schemas import specialist_schema
from council.models import CallUsage, Hypothesis, Incident, SpecialistName

SYSTEM = build_system(
    role="unique charge de l'investigation",
    sees=(
        "TOUT ce qui est disponible sur cet incident : les metriques systeme et "
        "les changements recents, les journaux applicatifs et les piles "
        "d'exception, et les fiches d'incidents passes les plus proches. Le taux "
        "d'erreur est eleve dans tous les incidents qu'on te soumet : c'est le "
        "symptome qui a declenche l'alerte, pas un indice sur la cause."
    ),
)

INSTRUCTION = (
    "Voici l'integralite du contexte de l'incident. Croise les trois sources et "
    "conclus directement."
)


class BaselineAgent:
    name = SpecialistName.BASELINE
    system = SYSTEM

    def __init__(self, retriever: CaseRetriever, k: int = 5) -> None:
        self.retriever = retriever
        self.k = k

    def build_user(self, incident: Incident) -> str:
        cases = self.retriever.search(incident.history_query(), k=self.k)
        view = {
            "incident_id": incident.id,
            "service": incident.service,
            "started_at": incident.started_at.isoformat(),
            "summary": incident.summary,
            "metrics": incident.metrics.model_dump(mode="json"),
            "logs": incident.logs.model_dump(mode="json"),
            "fiches_historiques": [
                {
                    "id": case.entry.id,
                    "titre": case.entry.title,
                    "symptomes": case.entry.symptoms,
                    "diagnostic": case.entry.diagnosis,
                    "cause_retenue": case.entry.root_cause.value,
                }
                for case in cases
            ],
        }
        return f"{INSTRUCTION}\n\n```json\n{json.dumps(view, ensure_ascii=False, indent=2)}\n```"

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "high"
    ) -> tuple[Hypothesis, CallUsage]:
        payload, usage = client.structured(
            system=self.system,
            user=self.build_user(incident),
            schema=specialist_schema(),
            effort=effort,
            tag=f"baseline:{effort}:{incident.id}",
        )
        return parse_hypothesis(self.name, payload), usage

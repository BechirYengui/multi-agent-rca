"""Socle commun aux trois specialistes.

**Choix d'integrite, a garder en tete en lisant les invites** : aucune consigne
ne contient de guide de discrimination entre causes proches. On ne dit nulle
part que « le pic de trafic fait monter `rps` en premier » ou que « l'attente du
pool est locale alors que le timeout aval ne l'est pas ». Ces regles sont
exactement celles qui ont servi a FABRIQUER le jeu de donnees : les injecter
reviendrait a transmettre la grille de correction aux agents evalues, et le
benchmark ne mesurerait plus que la fidelite du modele a une consigne.

Le modele dispose de sa propre connaissance des incidents de production. C'est
elle qu'on evalue.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from council.data.taxonomy import RootCause
from council.llm.client import LLMClient
from council.llm.schemas import ABSTENTION, cause_catalogue, specialist_schema
from council.models import CallUsage, Hypothesis, Incident, SpecialistName

COMMON_RULES = """Regles, sans exception :

1. N'invente aucune observation. Chaque element de `evidence` doit etre une
   valeur ou une phrase que tu as reellement lue dans les donnees ci-dessous.
2. Si ce que tu vois ne permet pas de trancher, reponds `{abstention}` avec une
   confiance de 0. Ne devine pas : une abstention est une information utile a
   l'arbitre, une hypothese inventee le trompe.
3. `confidence` est la probabilite que ta cause soit la bonne. 0,9 veut dire que
   tu te trompes une fois sur dix. Sois calibre, pas poli.
4. `alternatives` : au plus deux autres causes compatibles avec ce que tu vois,
   par ordre decroissant de vraisemblance.
5. `reasoning` : trois phrases au maximum."""


def build_system(role: str, sees: str) -> str:
    return f"""Tu participes a l'analyse d'un incident de production. Tu es l'agent {role}.

Ce que tu vois : {sees}

Ce que tu ne vois pas : les autres sources d'information sont confiees a d'autres
agents qui travaillent en parallele, sans te consulter et sans que tu saches ce
qu'ils concluent. C'est deliberé : si vos conclusions se rejoignent, l'accord
doit etre un signal, pas un effet d'entrainement.

Tu proposes UNE cause racine, prise dans cette liste fermee :
{cause_catalogue()}

{COMMON_RULES.format(abstention=ABSTENTION)}"""


def parse_hypothesis(agent: SpecialistName, payload: dict[str, Any]) -> Hypothesis:
    raw_cause = payload["cause"]
    cause = None if raw_cause == ABSTENTION else RootCause(raw_cause)
    confidence = float(payload["confidence"])
    if cause is None:
        # Une abstention assortie d'une confiance elevee n'a pas de sens ; on la
        # ramene a 0 plutot que de laisser le chiffre polluer la calibration.
        confidence = 0.0
    alternatives = [RootCause(value) for value in payload.get("alternatives", [])][:2]
    return Hypothesis(
        agent=agent,
        cause=cause,
        confidence=max(0.0, min(1.0, confidence)),
        evidence=[str(item) for item in payload.get("evidence", [])],
        alternatives=alternatives,
        reasoning=str(payload.get("reasoning", "")),
    )


def render_user_message(view: dict[str, Any], instruction: str) -> str:
    return f"{instruction}\n\n```json\n{json.dumps(view, ensure_ascii=False, indent=2)}\n```"


FOLLOWUP_TEMPLATE = """{question}

Reponds au meme format. Si tu maintiens ta conclusion, dis dans `reasoning` ce
qui, dans TES donnees, resiste a cette objection. Si tu ne peux pas repondre avec
ce que tu as, abstiens-toi plutot que de te rallier."""


class Specialist(Protocol):
    name: SpecialistName
    system: str

    def build_user(self, incident: Incident) -> str: ...

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "low"
    ) -> tuple[Hypothesis, CallUsage]: ...


class BaseSpecialist:
    """Implemente une fois pour toutes l'appel et la relance.

    La relance reprend EXACTEMENT la meme vue que le premier appel, augmentee de
    la question de l'arbitre. L'agent divergent ne recoit jamais les donnees des
    autres : on lui demande de re-regarder les siennes, pas de se rallier a une
    information qu'il n'a pas les moyens de verifier.
    """

    name: SpecialistName
    system: str

    def build_user(self, incident: Incident) -> str:  # pragma: no cover - abstrait
        raise NotImplementedError

    def _call(
        self, incident: Incident, client: LLMClient, effort: str, user: str, tag: str
    ) -> tuple[Hypothesis, CallUsage]:
        payload, usage = client.structured(
            system=self.system,
            user=user,
            schema=specialist_schema(),
            effort=effort,
            tag=tag,
        )
        return parse_hypothesis(self.name, payload), usage

    def analyse(
        self, incident: Incident, client: LLMClient, effort: str = "low"
    ) -> tuple[Hypothesis, CallUsage]:
        return self._call(
            incident, client, effort, self.build_user(incident), f"{self.name}:{incident.id}"
        )

    def reask(
        self, incident: Incident, client: LLMClient, effort: str, question: str, round_index: int
    ) -> tuple[Hypothesis, CallUsage]:
        user = (
            self.build_user(incident) + "\n\n---\n\n" + FOLLOWUP_TEMPLATE.format(question=question)
        )
        return self._call(
            incident, client, effort, user, f"{self.name}:{incident.id}:r{round_index}"
        )

"""L'arbitre : il synthetise, il relance, ou il refuse de trancher.

Trois taches, trois schemas, trois appels distincts -- jamais un seul appel
fourre-tout. La raison est mesurable : un schema qui autorise a la fois « voici
la cause » et « je ne sais pas » laisse le modele choisir la sortie confortable.
Ici, c'est le routeur (deterministe, teste) qui decide de la tache ; l'arbitre ne
fait que l'executer.

Ce que l'arbitre ne voit jamais : les donnees brutes. Il ne recoit que les trois
hypotheses, leurs preuves citees et leurs confiances. S'il pouvait relire les
metriques, il redeviendrait un agent unique avec trois resumes en plus, et la
comparaison au bras « baseline » perdrait son sens.
"""

from __future__ import annotations

import json
from typing import Any

from council.data.taxonomy import LABEL_FR, RootCause
from council.llm.client import LLMClient
from council.llm.schemas import (
    arbiter_question_schema,
    arbiter_split_schema,
    arbiter_verdict_schema,
    cause_catalogue,
)
from council.models import CallUsage, Hypothesis, RejectedTrack, SpecialistName, Track
from council.orchestration.routing import RoutingDecision

SYSTEM = f"""Tu es l'arbitre d'une investigation d'incident de production.

Trois agents ont analyse l'incident en parallele, chacun sur une source
differente et sans se consulter :
- `infra` : metriques systeme et changements recents ;
- `app` : journaux applicatifs et piles d'exception ;
- `history` : incidents passes deja resolus, retrouves par similarite.

Tu ne vois pas les donnees brutes. Tu ne vois que leurs conclusions, les preuves
qu'ils citent et la confiance qu'ils annoncent. Tu ne peux donc pas refaire leur
travail : tu peux seulement peser ce qu'ils rapportent.

Deux principes :
1. Un agent qui s'abstient n'est pas un agent qui contredit. Une abstention
   signifie que sa source ne contient rien d'exploitable, pas qu'il est en
   desaccord.
2. Le nombre d'agents qui soutiennent une cause compte, mais la QUALITE des
   preuves citees compte davantage. Un agent seul qui cite trois observations
   chiffrees vaut mieux que deux agents qui n'en citent aucune.

Liste fermee des causes :
{cause_catalogue()}"""


def render_hypotheses(hypotheses: dict[SpecialistName, Hypothesis]) -> str:
    payload = [
        {
            "agent": agent.value,
            "cause": None if h.cause is None else h.cause.value,
            "cause_en_clair": None if h.cause is None else LABEL_FR[h.cause],
            "confiance_annoncee": h.confidence,
            "preuves_citees": h.evidence,
            "alternatives": [alt.value for alt in h.alternatives],
            "raisonnement": h.reasoning,
        }
        for agent, h in hypotheses.items()
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _context(decision: RoutingDecision, hypotheses: dict[SpecialistName, Hypothesis]) -> str:
    return (
        f"Forme de l'accord constatee mecaniquement : {decision.kind.value} "
        f"({decision.answered} agent(s) se sont prononces, "
        f"{decision.abstained} se sont abstenus).\n"
        f"Motif du routage : {decision.reason}\n\n"
        f"```json\n{render_hypotheses(hypotheses)}\n```"
    )


class Arbiter:
    def __init__(self, effort: str = "high") -> None:
        self.effort = effort

    def synthesize(
        self,
        incident_id: str,
        hypotheses: dict[SpecialistName, Hypothesis],
        decision: RoutingDecision,
        client: LLMClient,
    ) -> tuple[RootCause, float, list[RejectedTrack], str, CallUsage]:
        user = (
            _context(decision, hypotheses)
            + "\n\nRetiens une cause et une seule. Dans `rejected`, liste CHAQUE autre "
            "cause proposee par un agent, avec le motif precis pour lequel tu l'ecartes. "
            "Ta `confidence` doit refleter la probabilite que ta conclusion soit juste."
        )
        payload, usage = client.structured(
            system=SYSTEM,
            user=user,
            schema=arbiter_verdict_schema(),
            effort=self.effort,
            tag=f"arbiter:synthesize:{incident_id}",
        )
        rejected = [
            RejectedTrack(cause=RootCause(item["cause"]), reason=item["reason"])
            for item in payload.get("rejected", [])
        ]
        confidence = max(0.0, min(1.0, float(payload["confidence"])))
        return RootCause(payload["cause"]), confidence, rejected, payload["reasoning"], usage

    def formulate_question(
        self,
        incident_id: str,
        hypotheses: dict[SpecialistName, Hypothesis],
        decision: RoutingDecision,
        client: LLMClient,
        round_index: int,
    ) -> tuple[str, CallUsage]:
        assert decision.divergent is not None
        user = (
            _context(decision, hypotheses)
            + f"\n\nL'agent `{decision.divergent.value}` diverge. Formule UNE question "
            f"precise a lui poser, a laquelle il puisse repondre avec ses seules "
            f"donnees. Ne lui demande pas de commenter les conclusions des autres : "
            f"il n'a aucun moyen de les verifier. Demande-lui une observation "
            f"supplementaire, ou ce qui dans ses donnees resiste a l'hypothese "
            f"majoritaire ({decision.leading_cause})."
        )
        payload, usage = client.structured(
            system=SYSTEM,
            user=user,
            schema=arbiter_question_schema(),
            effort=self.effort,
            tag=f"arbiter:question:{incident_id}:r{round_index}",
        )
        return str(payload["question"]), usage

    def report_split(
        self,
        incident_id: str,
        hypotheses: dict[SpecialistName, Hypothesis],
        decision: RoutingDecision,
        client: LLMClient,
    ) -> tuple[list[Track], str, str, CallUsage]:
        user = (
            _context(decision, hypotheses)
            + "\n\nLes analyses ne convergent pas. NE TRANCHE PAS. Restitue chaque piste "
            "avec sa confiance propre et ce qui la soutient, puis indique dans "
            "`next_step` l'observation qui les departagerait. Un choix arbitraire ici "
            "coute plus cher qu'un rapport honnete."
        )
        payload, usage = client.structured(
            system=SYSTEM,
            user=user,
            schema=arbiter_split_schema(),
            effort=self.effort,
            tag=f"arbiter:split:{incident_id}",
        )
        supporters: dict[str, list[SpecialistName]] = {}
        for agent, hypothesis in hypotheses.items():
            if hypothesis.cause is not None:
                supporters.setdefault(hypothesis.cause.value, []).append(agent)
        tracks = [
            Track(
                cause=RootCause(item["cause"]),
                confidence=max(0.0, min(1.0, float(item["confidence"]))),
                supported_by=supporters.get(item["cause"], []),
                summary=item["summary"],
            )
            for item in payload.get("tracks", [])
        ]
        return tracks, str(payload["next_step"]), str(payload["reasoning"]), usage


def arbiter_payload_keys() -> dict[str, Any]:  # pragma: no cover - aide au debogage
    return {
        "synthesize": arbiter_verdict_schema(),
        "question": arbiter_question_schema(),
        "split": arbiter_split_schema(),
    }

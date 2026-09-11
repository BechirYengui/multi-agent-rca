"""La decision de routage, en fonction pure.

C'est deliberement la seule partie de l'orchestration qui ne depend ni de
LangGraph, ni d'un appel LLM, ni du temps. La question metier -- y a-t-il
consensus, et si non, faut-il relancer quelqu'un ou publier plusieurs pistes ? --
se teste alors exhaustivement en memoire, en millisecondes. LangGraph ne fait
plus que du cablage.

Deux regles qui ne sont pas evidentes :

1. **Une abstention n'est pas un desaccord.** Un agent qui n'a rien vu ne
   contredit personne : il est retire du decompte, pas compte contre la
   majorite. Sans cela, les onze incidents ou deux agents sur trois n'ont
   structurellement rien a voir seraient tous classes « desaccord total ».
2. **Le plafond de relances est applique ICI, dans le routeur**, et pas dans le
   noeud de clarification. Une boucle infinie facturee est le mode de panne
   qu'on refuse d'avoir, et un plafond applique par le noeud qu'il limite est un
   plafond qu'on oublie de brancher.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from council.data.taxonomy import RootCause
from council.models import ConsensusKind, Hypothesis, SpecialistName


class Route(StrEnum):
    CONCLUDE = "conclude"
    CLARIFY = "clarify"
    REPORT_SPLIT = "report_split"


# Plafond de confiance finale selon la FORME de l'accord.
#
# La confiance auto-declaree par un modele n'est pas fiable tant que
# `docs/calibration.md` n'a pas montre le contraire ; la forme de l'accord, elle,
# est une donnee structurelle observee. Ces plafonds sont donc provisoires et
# seront cales sur la calibration -- ils sont ici pour que le systeme ne puisse
# pas annoncer 0,95 sur le temoignage d'un seul agent.
CONFIDENCE_CEILING: dict[ConsensusKind, float] = {
    ConsensusKind.UNANIMOUS: 1.00,
    ConsensusKind.CONVERGENT_PARTIAL: 0.85,
    ConsensusKind.MAJORITY: 0.75,
    ConsensusKind.SINGLE_SOURCE: 0.60,
    ConsensusKind.SPLIT: 0.0,
    ConsensusKind.NONE: 0.0,
}


@dataclass(frozen=True)
class RoutingDecision:
    kind: ConsensusKind
    route: Route
    leading_cause: RootCause | None
    support: int
    answered: int
    abstained: int
    divergent: SpecialistName | None
    reason: str

    @property
    def ceiling(self) -> float:
        return CONFIDENCE_CEILING[self.kind]


def latest_by_agent(hypotheses: list[Hypothesis]) -> dict[SpecialistName, Hypothesis]:
    """Apres une relance, un agent a deux hypotheses : seule la derniere compte."""
    latest: dict[SpecialistName, Hypothesis] = {}
    for hypothesis in hypotheses:
        latest[hypothesis.agent] = hypothesis
    return latest


def decide(
    hypotheses: list[Hypothesis], rounds_used: int = 0, max_rounds: int = 2
) -> RoutingDecision:
    current = latest_by_agent(hypotheses)
    answers = {
        agent: hypothesis for agent, hypothesis in current.items() if hypothesis.cause is not None
    }
    abstained = len(current) - len(answers)

    if not answers:
        return RoutingDecision(
            kind=ConsensusKind.NONE,
            route=Route.REPORT_SPLIT,
            leading_cause=None,
            support=0,
            answered=0,
            abstained=abstained,
            divergent=None,
            reason="aucun agent n'a d'element exploitable",
        )

    counts = Counter(hypothesis.cause for hypothesis in answers.values())
    leading_cause, support = counts.most_common(1)[0]
    assert leading_cause is not None

    if len(answers) == 1:
        agent = next(iter(answers))
        return RoutingDecision(
            kind=ConsensusKind.SINGLE_SOURCE,
            route=Route.CONCLUDE,
            leading_cause=leading_cause,
            support=1,
            answered=1,
            abstained=abstained,
            divergent=None,
            reason=f"seul l'agent {agent} dispose d'elements ; les autres s'abstiennent",
        )

    if support == len(answers):
        kind = ConsensusKind.UNANIMOUS if support == 3 else ConsensusKind.CONVERGENT_PARTIAL
        return RoutingDecision(
            kind=kind,
            route=Route.CONCLUDE,
            leading_cause=leading_cause,
            support=support,
            answered=len(answers),
            abstained=abstained,
            divergent=None,
            reason=(
                f"les {support} agents qui ont repondu convergent vers {leading_cause}"
                + (f" ({abstained} abstention(s))" if abstained else "")
            ),
        )

    if support == 1:
        return RoutingDecision(
            kind=ConsensusKind.SPLIT,
            route=Route.REPORT_SPLIT,
            leading_cause=None,
            support=1,
            answered=len(answers),
            abstained=abstained,
            divergent=None,
            reason=(
                f"{len(answers)} hypotheses, {len(answers)} causes differentes : "
                f"aucun choix ne serait autre chose qu'arbitraire"
            ),
        )

    divergent = next(
        agent for agent, hypothesis in answers.items() if hypothesis.cause != leading_cause
    )
    if rounds_used >= max_rounds:
        return RoutingDecision(
            kind=ConsensusKind.MAJORITY,
            route=Route.CONCLUDE,
            leading_cause=leading_cause,
            support=support,
            answered=len(answers),
            abstained=abstained,
            divergent=divergent,
            reason=(
                f"{support} agents pour {leading_cause}, l'agent {divergent} maintient "
                f"son desaccord apres {rounds_used} relance(s) : on tranche sans lui"
            ),
        )
    return RoutingDecision(
        kind=ConsensusKind.MAJORITY,
        route=Route.CLARIFY,
        leading_cause=leading_cause,
        support=support,
        answered=len(answers),
        abstained=abstained,
        divergent=divergent,
        reason=(
            f"{support} agents pour {leading_cause}, l'agent {divergent} diverge : "
            f"relance {rounds_used + 1}/{max_rounds} avant de trancher"
        ),
    )

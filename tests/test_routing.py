"""Table de verite complete du routeur. Aucun LLM, aucun LangGraph, aucune horloge.

Si cette table est juste, l'orchestration ne peut plus se tromper que de cablage.
"""

from __future__ import annotations

import pytest

from council.data.taxonomy import RootCause as C
from council.models import ConsensusKind, Hypothesis
from council.models import SpecialistName as S
from council.orchestration.routing import (
    CONFIDENCE_CEILING,
    Route,
    decide,
    latest_by_agent,
)


def h(agent: S, cause: C | None, confidence: float = 0.7, evidence: int = 2) -> Hypothesis:
    return Hypothesis(
        agent=agent,
        cause=cause,
        confidence=0.0 if cause is None else confidence,
        evidence=[f"preuve {i}" for i in range(evidence)],
        alternatives=[],
        reasoning="",
    )


def test_les_trois_convergent() -> None:
    decision = decide([h(S.INFRA, C.DISK_FULL), h(S.APP, C.DISK_FULL), h(S.HISTORY, C.DISK_FULL)])
    assert decision.kind is ConsensusKind.UNANIMOUS
    assert decision.route is Route.CONCLUDE
    assert decision.leading_cause is C.DISK_FULL
    assert decision.support == 3
    assert decision.divergent is None


def test_deux_convergent_le_troisieme_s_abstient() -> None:
    """Ce n'est PAS l'unanimite : deux voix, pas trois. Le plafond de confiance baisse."""
    decision = decide([h(S.INFRA, C.DISK_FULL), h(S.APP, C.DISK_FULL), h(S.HISTORY, None)])
    assert decision.kind is ConsensusKind.CONVERGENT_PARTIAL
    assert decision.route is Route.CONCLUDE
    assert decision.support == 2
    assert decision.abstained == 1
    assert decision.ceiling < CONFIDENCE_CEILING[ConsensusKind.UNANIMOUS]


def test_deux_convergent_un_diverge_declenche_une_relance() -> None:
    decision = decide([h(S.INFRA, C.DISK_FULL), h(S.APP, C.DISK_FULL), h(S.HISTORY, C.MEMORY_LEAK)])
    assert decision.kind is ConsensusKind.MAJORITY
    assert decision.route is Route.CLARIFY
    assert decision.leading_cause is C.DISK_FULL
    assert decision.divergent is S.HISTORY


@pytest.mark.parametrize("rounds_used", [2, 3, 10])
def test_le_plafond_de_relances_est_applique_dans_le_routeur(rounds_used: int) -> None:
    """Une boucle infinie facturee est le mode de panne qu'on refuse d'avoir."""
    decision = decide(
        [h(S.INFRA, C.DISK_FULL), h(S.APP, C.DISK_FULL), h(S.HISTORY, C.MEMORY_LEAK)],
        rounds_used=rounds_used,
        max_rounds=2,
    )
    assert decision.route is Route.CONCLUDE
    assert decision.kind is ConsensusKind.MAJORITY
    assert decision.divergent is S.HISTORY


def test_les_trois_divergent_aucun_choix_force() -> None:
    decision = decide(
        [h(S.INFRA, C.DISK_FULL), h(S.APP, C.MEMORY_LEAK), h(S.HISTORY, C.CERT_EXPIRY)]
    )
    assert decision.kind is ConsensusKind.SPLIT
    assert decision.route is Route.REPORT_SPLIT
    assert decision.leading_cause is None
    assert decision.ceiling == 0.0


def test_deux_hypotheses_opposees_et_une_abstention_restent_un_desaccord() -> None:
    decision = decide([h(S.INFRA, C.DISK_FULL), h(S.APP, C.MEMORY_LEAK), h(S.HISTORY, None)])
    assert decision.kind is ConsensusKind.SPLIT
    assert decision.route is Route.REPORT_SPLIT


def test_une_seule_voix_conclut_mais_sous_plafond() -> None:
    """Le cas des incidents ou seule la base historique porte l'information."""
    decision = decide([h(S.INFRA, None), h(S.APP, None), h(S.HISTORY, C.CACHE_STAMPEDE)])
    assert decision.kind is ConsensusKind.SINGLE_SOURCE
    assert decision.route is Route.CONCLUDE
    assert decision.leading_cause is C.CACHE_STAMPEDE
    assert decision.abstained == 2
    assert decision.ceiling == pytest.approx(0.60)


def test_personne_n_a_rien_vu() -> None:
    decision = decide([h(S.INFRA, None), h(S.APP, None), h(S.HISTORY, None)])
    assert decision.kind is ConsensusKind.NONE
    assert decision.route is Route.REPORT_SPLIT
    assert decision.leading_cause is None


def test_apres_relance_seule_la_derniere_hypothese_compte() -> None:
    hypotheses = [
        h(S.INFRA, C.DISK_FULL),
        h(S.APP, C.DISK_FULL),
        h(S.HISTORY, C.MEMORY_LEAK),
        h(S.HISTORY, C.DISK_FULL),  # l'agent revise apres la relance
    ]
    assert latest_by_agent(hypotheses)[S.HISTORY].cause is C.DISK_FULL
    decision = decide(hypotheses, rounds_used=1)
    assert decision.kind is ConsensusKind.UNANIMOUS
    assert decision.route is Route.CONCLUDE


def test_les_plafonds_de_confiance_sont_ordonnes() -> None:
    """L'ordre encode la these : plus l'accord est large, plus on peut affirmer."""
    assert (
        CONFIDENCE_CEILING[ConsensusKind.UNANIMOUS]
        > CONFIDENCE_CEILING[ConsensusKind.CONVERGENT_PARTIAL]
        > CONFIDENCE_CEILING[ConsensusKind.MAJORITY]
        > CONFIDENCE_CEILING[ConsensusKind.SINGLE_SOURCE]
        > CONFIDENCE_CEILING[ConsensusKind.SPLIT]
    )


def test_chaque_decision_porte_sa_raison() -> None:
    """La trace doit pouvoir expliquer POURQUOI, pas seulement QUOI."""
    for hypotheses in (
        [h(S.INFRA, C.DISK_FULL), h(S.APP, C.DISK_FULL), h(S.HISTORY, C.DISK_FULL)],
        [h(S.INFRA, C.DISK_FULL), h(S.APP, C.MEMORY_LEAK), h(S.HISTORY, C.CERT_EXPIRY)],
        [h(S.INFRA, None), h(S.APP, None), h(S.HISTORY, None)],
    ):
        assert len(decide(hypotheses).reason) > 20

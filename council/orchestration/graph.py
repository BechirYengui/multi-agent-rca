"""Cablage LangGraph. Rien d'autre : ce que font les noeuds est dans `nodes.py`.

    START ─┬─> infra   ─┐
           ├─> app     ─┼─> route ─┬─> conclude ──> END
           └─> history ─┘    ▲     ├─> clarify ──┘ (retour vers route)
                             └─────┘     └─> split ──> END

Le fan-out tient dans les trois aretes depuis START : LangGraph execute les
branches d'un meme super-pas en parallele. Le fan-in tient dans les reducteurs
`operator.add` de l'etat (`state.py`) : `route` attend les trois avant de partir.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from council.agents.arbiter import Arbiter
from council.agents.base import BaseSpecialist
from council.llm.client import LLMClient
from council.models import Incident, SpecialistName, Verdict
from council.orchestration.nodes import CouncilNodes
from council.orchestration.routing import Route
from council.orchestration.state import InvestigationState
from council.orchestration.trace import Tracer

SPECIALIST_NODES = (SpecialistName.INFRA, SpecialistName.APP, SpecialistName.HISTORY)


def build_graph(
    specialists: Sequence[BaseSpecialist],
    arbiter: Arbiter,
    client: LLMClient,
    tracer: Tracer,
    effort_specialist: str = "low",
    max_rounds: int = 2,
) -> Any:
    nodes = CouncilNodes(
        specialists=specialists,
        arbiter=arbiter,
        client=client,
        tracer=tracer,
        effort_specialist=effort_specialist,
        max_rounds=max_rounds,
    )

    graph: Any = StateGraph(InvestigationState)
    for name in SPECIALIST_NODES:
        graph.add_node(name.value, nodes.specialist(name))
    graph.add_node("route", nodes.route)
    graph.add_node("clarify", nodes.clarify)
    graph.add_node("conclude", nodes.conclude)
    graph.add_node("split", nodes.split)

    for name in SPECIALIST_NODES:
        graph.add_edge(START, name.value)
        graph.add_edge(name.value, "route")

    graph.add_conditional_edges(
        "route",
        lambda state: str(state["route"]),
        {
            Route.CONCLUDE.value: "conclude",
            Route.CLARIFY.value: "clarify",
            Route.REPORT_SPLIT.value: "split",
        },
    )
    graph.add_edge("clarify", "route")
    graph.add_edge("conclude", END)
    graph.add_edge("split", END)
    return graph.compile()


def investigate_state(graph: Any, incident: Incident) -> dict[str, Any]:
    """Etat final complet.

    Le benchmark en a besoin : le bras « vote » se derive des hypotheses du
    PREMIER tour, sans un appel de plus.
    """
    final: dict[str, Any] = graph.invoke(
        {"incident": incident, "hypotheses": [], "clarifications": [], "usages": [], "rounds": 0}
    )
    return final


def investigate(graph: Any, incident: Incident) -> Verdict:
    verdict: Verdict = investigate_state(graph, incident)["verdict"]
    return verdict

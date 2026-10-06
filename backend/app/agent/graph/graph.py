"""Graph assembly: the request-level production workflow.

The request-level production graph has these top-level stages:

``START → load_context → route_capability → {understand | direct workflow}``
``→ parse_validate → decide_turn``
``decide_turn → {retrieve | mutation | answer}``
``retrieve → answer``, ``mutation → answer``, ``answer → respond → END``.

Each HTTP request runs one fresh graph from ``START`` to ``END``. There is no
checkpoint, no interrupt, no resume command and no back edge: multi-turn dialogue
is persisted in the existing business session store (messages, task/plan,
pending questions, displayed candidates), and ``load_context`` re-reads it on
every request. The only business write is ``respond`` (via
``turn_commit.commit_graph_turn``).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph.nodes.answer import answer
from app.agent.graph.nodes.capability import route_after_capability, route_capability
from app.agent.graph.nodes.context import load_context
from app.agent.graph.nodes.mutation import mutation
from app.agent.graph.nodes.respond import respond
from app.agent.graph.nodes.retrieve import retrieve
from app.agent.graph.nodes.workflow import (
    direct_product_filter_workflow,
    direct_product_type_workflow,
)
from app.agent.graph.nodes.understand import (
    decide_turn,
    parse_validate,
    route_after_decision,
    understand,
)
from app.agent.graph.runtime import TurnRuntime
from app.agent.graph.state import GraphState

#: The production nodes, in contract order. ``load_context`` is the entry.
PRODUCTION_NODES: tuple[str, ...] = (
    "load_context",
    "route_capability",
    "direct_product_type_workflow",
    "direct_product_filter_workflow",
    "understand",
    "parse_validate",
    "decide_turn",
    "retrieve",
    "mutation",
    "answer",
    "respond",
)


def build_graph() -> StateGraph:
    """Build the request-level graph. Compiling it never calls the model."""
    graph = StateGraph(GraphState, context_schema=TurnRuntime)
    for name, fn in (
        ("load_context", load_context),
        ("route_capability", route_capability),
        ("direct_product_type_workflow", direct_product_type_workflow),
        ("direct_product_filter_workflow", direct_product_filter_workflow),
        ("understand", understand),
        ("parse_validate", parse_validate),
        ("decide_turn", decide_turn),
        ("retrieve", retrieve),
        ("mutation", mutation),
        ("answer", answer),
        ("respond", respond),
    ):
        graph.add_node(name, fn)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "route_capability")
    graph.add_conditional_edges(
        "route_capability",
        route_after_capability,
        {
            "understand": "understand",
            "direct_product_type_workflow": "direct_product_type_workflow",
            "direct_product_filter_workflow": "direct_product_filter_workflow",
        },
    )
    graph.add_edge("understand", "parse_validate")
    graph.add_edge("direct_product_type_workflow", "parse_validate")
    graph.add_edge("direct_product_filter_workflow", "parse_validate")
    graph.add_edge("parse_validate", "decide_turn")
    graph.add_conditional_edges(
        "decide_turn",
        route_after_decision,
        {
            "retrieve": "retrieve",
            "mutation": "mutation",
            "chat": "answer",
            "answer": "answer",
            "clarify": "answer",
            "refuse": "answer",
        },
    )
    graph.add_edge("retrieve", "answer")
    graph.add_edge("mutation", "answer")
    graph.add_edge("answer", "respond")
    graph.add_edge("respond", END)
    return graph


def get_graph() -> CompiledStateGraph:
    """Compile the production graph. A fresh request enters it at ``START``."""
    return build_graph().compile()


__all__ = ["PRODUCTION_NODES", "build_graph", "get_graph"]

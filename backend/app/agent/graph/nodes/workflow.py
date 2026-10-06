"""Directly compile a verified structured product-type answer into a Proposal."""

from __future__ import annotations

from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, update_partition
from app.agent.turn_context_plan import product_filter_selection


def direct_product_type_workflow(
    state: GraphState, runtime: TurnRuntime
) -> dict[str, Any]:
    """Reuse the selected server option as a read-only category exploration."""
    runtime = context_of(runtime)
    answer = runtime.clarification_answer
    label = answer["option"]["label"]
    proposal = {
        "target": {"kind": "category", "name": label, "intent": "explore"},
        "lookups": [{"kind": "product", "query": label}],
        "resolved_questions": [answer["question_id"]],
    }
    return update_partition(state, "turn", proposal=proposal)


def direct_product_filter_workflow(
    state: GraphState, runtime: TurnRuntime
) -> dict[str, Any]:
    """Reuse the selected verified filter as a read-only constrained lookup."""
    runtime = context_of(runtime)
    answer = runtime.clarification_answer
    selection = product_filter_selection(answer["option"]["id"])
    query = selection["query"]
    proposal = {
        "target": {"kind": "category", "name": query, "intent": "explore"},
        "constraints": {"specification": selection["specification"]},
        "lookups": [{"kind": "product", "query": query}],
        "resolved_questions": [answer["question_id"]],
    }
    return update_partition(state, "turn", proposal=proposal)


__all__ = ["direct_product_filter_workflow", "direct_product_type_workflow"]

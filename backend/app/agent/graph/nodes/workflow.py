"""Directly compile a verified structured product-type answer into a Proposal."""

from __future__ import annotations

from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, update_partition


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


__all__ = ["direct_product_type_workflow"]

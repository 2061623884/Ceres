"""``respond``: the one transaction, then the final SSE for its committed result.

This node is the only place a Guide request writes business authority. It calls
``commit_graph_turn``, which:

1. validates inside the transaction (the authoritative guard against the
   request's own stored expectations, with a write lock);
2. atomically saves the authorized plan change, the target/conditions/pending/
   displayed candidates, the user and assistant messages and the final
   response/idempotency receipt;
3. only after that commit emits the matching SSE events.

A validation failure commits neither the contradictory business change nor the
receipt: the receipt is written as the refusal it really was.
"""

from __future__ import annotations

from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, update_partition
from app.agent.graph.turn_commit import commit_graph_turn


def respond(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    runtime = context_of(runtime)
    receipt = commit_graph_turn(state, runtime)
    runtime.response = receipt
    return update_partition(
        state,
        "result",
        receipt={
            "request_id": receipt.get("request_id"),
            "assistant_message_id": receipt.get("assistant_message_id"),
            "message_sequence": receipt.get("message_sequence"),
            "task_id": receipt.get("task_id"),
            "status": receipt.get("status"),
        },
        committed=bool(receipt.get("committed")),
        plan_effect=str(receipt.get("plan_effect") or "keep"),
        response=None,
    )


__all__ = ["respond"]

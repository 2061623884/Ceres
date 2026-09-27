"""``retrieve``: one real, read-only round of facts.

The node serves the read requests the parsed proposal carried, through the
existing :class:`~app.agent.tools.read.ReadTools` port. It writes nothing: no
plan, no cart, no session state. Its only outgoing edge is ``answer``, which
composes the reply from the fetched facts — there is no loop back to the model
and no general tool-repair cycle.
"""

from __future__ import annotations

from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, update_partition
from app.agent.turn_primitives import clamp_limits
from app.agent.graph.nodes.understand import timeout_error


def retrieve(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Serve this request's read requests once, then hand control to ``answer``."""
    runtime = context_of(runtime)
    turn = state["turn"]
    if turn.get("halt"):
        return {}

    if runtime.reads is None:
        raise ValueError("READ_PORT_REQUIRED: the runtime context must carry a read port")

    _max_calls, lookup_limit = clamp_limits(runtime.budget)
    proposal = turn["parsed_proposal"]

    runtime.on_phase("retrieve")
    if runtime.stop():
        return update_partition(state, "turn", halt="stopped")
    if runtime.expired():
        return update_partition(
            state, "turn", halt="timed_out", error=timeout_error()
        )

    results = runtime.reads.serve(proposal, runtime.candidates, lookup_limit=lookup_limit)
    updates: dict[str, Any] = {
        "read_results": [*(turn.get("read_results") or []), *results]
    }
    if runtime.stop():
        return update_partition(state, "turn", halt="stopped", **updates)
    if runtime.expired():
        return update_partition(
            state, "turn", halt="timed_out", error=timeout_error(), **updates
        )
    return update_partition(state, "turn", **updates)


__all__ = ["retrieve"]

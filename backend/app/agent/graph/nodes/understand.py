"""The one-turn model, validation, and decision boundary.

``understand`` obtains a raw Proposal, ``parse_validate`` checks its protocol,
and ``decide_turn`` alone joins the validated semantics with server facts. The
Graph then consumes ``TurnDecision.route`` without interpreting Proposal again.
There is no repair loop or additional route layer.
"""

from __future__ import annotations

import time
from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, merge_state, update_partition
from app.agent.protocol import SemanticProtocolError, parse_proposal
from app.agent.turn_primitives import (
    CALL_TIMEOUT_CAPABILITY,
    TIMEOUT_CODE,
    build_request,
    clamp_limits,
    evaluate_gate,
)
from app.llm.errors import LLMProviderError
from app.schemas.goal import TurnDecision


class Halt(Exception):
    """An early, honest end of the turn (stop / deadline / budget / failure)."""

    def __init__(self, reason: str, error: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.error = error


def timeout_error() -> dict[str, Any]:
    return {
        "code": TIMEOUT_CODE,
        "message": "本轮处理超时，未执行的修改没有写入。",
        "retryable": True,
    }


def understanding_error(exc: SemanticProtocolError) -> dict[str, Any]:
    return {
        "code": exc.code,
        "message": exc.message,
        "retryable": bool(exc.retryable),
        "understanding": True,
    }


def halt_update(state: GraphState, reason: str, error: dict[str, Any] | None = None) -> dict[str, Any]:
    """End the turn; the ``answer`` node turns this into a refusal receipt."""
    return update_partition(state, "turn", halt=reason, error=error)


def propose_round(
    state: GraphState,
    runtime: TurnRuntime,
    *,
    query_results: list[dict[str, Any]] | None = None,
    read_only: bool = False,
) -> tuple[dict[str, Any] | None, int]:
    """One bounded, real provider call. Returns ``(raw_payload, calls_used)``.

    Raises :class:`Halt` for stop/deadline/budget/provider failure. A provider
    failure becomes a refusal receipt instead of a retry or another route.
    """
    turn = state["turn"]
    runtime = context_of(runtime)
    if runtime.provider is None:
        raise ValueError("PROVIDER_REQUIRED: the runtime context must carry a provider")

    calls = int(turn.get("model_calls") or 0)
    max_calls, _lookups = clamp_limits(runtime.budget)
    if calls >= max_calls:
        raise Halt(
            "failed",
            {
                "code": "MODEL_BUDGET_EXHAUSTED",
                "message": "本轮模型调用预算已用尽，没有执行新的模型请求。",
                "retryable": False,
                "understanding": True,
            },
        )
    if runtime.stop():
        raise Halt("stopped")
    if runtime.expired():
        raise Halt("timed_out", timeout_error())

    snapshot = runtime.snapshot_for(state["session"].get("turn_mode", "active"))
    request = build_request(
        snapshot,
        runtime.candidates,
        query_results=list(query_results or []),
        read_only=read_only,
    )
    remaining = runtime.remaining()
    if remaining is not None and remaining <= 0:
        raise Halt("timed_out", timeout_error())
    if remaining is not None:
        setter = getattr(runtime.provider, CALL_TIMEOUT_CAPABILITY, None)
        if callable(setter):
            setter(remaining)

    if calls == 0 and not read_only:
        # Parity with the old entry point, which announced the phase before the
        # first model request of the turn.
        runtime.on_phase("understanding")

    call_info = {
        "call_number": calls + 1,
        "stage": "answer" if read_only or calls > 0 else "understanding",
        "repair": False,
        "read_result_count": len(state["turn"].get("read_results") or []),
        "remaining_budget_s": round(remaining, 3) if remaining is not None else None,
    }
    # The model's prose is never streamed before the commit: a reply that
    # claims a change must not reach the shopper until the change is written.
    # Only progress events are emitted early; the final ``answer.delta`` is sent
    # after the commit transaction (``turn_commit._emit_transport_events``).
    runtime.on_model_call({**call_info, "status": "started"})
    started = time.monotonic()
    try:
        raw = runtime.provider.propose(request)
    except LLMProviderError as exc:
        runtime.on_model_call(
            {
                **call_info,
                "status": "failed",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "code": exc.code,
            }
        )
        if runtime.stop():
            raise Halt("stopped") from exc
        if runtime.expired():
            raise Halt("timed_out", timeout_error()) from exc
        # Provider failures are part of the same understanding boundary as
        # malformed output: convert them to a refusal receipt instead of
        # introducing a transport-level route or fallback branch.
        raise Halt(
            "failed",
            {
                "code": exc.code,
                "message": exc.message,
                "retryable": bool(exc.retryable),
                "understanding": True,
            },
        ) from exc
    else:
        runtime.on_model_call(
            {
                **call_info,
                "status": "completed",
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        )

    if runtime.stop():
        raise Halt("stopped")
    if runtime.expired():
        raise Halt("timed_out", timeout_error())
    return (raw if isinstance(raw, dict) else None), calls + 1


def route_from(decision: TurnDecision) -> str:
    """The Decision is the Graph's only route source."""
    return decision.route


def understand(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Call the provider and save its raw Proposal; no parsing or routing."""
    runtime = context_of(runtime)
    turn = state["turn"]
    if turn.get("halt"):
        return {}
    try:
        raw, calls = propose_round(state, runtime, query_results=[], read_only=False)
    except Halt as halt:
        return halt_update(state, halt.reason, halt.error)

    return update_partition(state, "turn", proposal=raw, model_calls=calls)


def parse_validate(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Parse the raw Proposal. Protocol/provider failures become refuse input."""
    raw = state["turn"].get("proposal")
    if state["turn"].get("halt"):
        return {}
    try:
        proposal = parse_proposal(raw)
    except SemanticProtocolError as exc:
        error = understanding_error(exc)
        return update_partition(state, "turn", halt="failed", error=error)
    if proposal.is_empty:
        empty = SemanticProtocolError("EMPTY_PROPOSAL", "模型没有给出任何可执行内容", retryable=True)
        error = understanding_error(empty)
        return update_partition(state, "turn", halt="failed", error=error)
    return update_partition(
        state,
        "turn",
        parsed_proposal=proposal,
        understanding=(
            proposal.understanding.model_dump(mode="json")
            if proposal.understanding is not None
            else None
        ),
        error=None,
    )


def decide_turn(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Compute the sole business route from the validated Proposal."""
    runtime = context_of(runtime)
    turn = state["turn"]
    if turn.get("halt") or turn.get("error"):
        error = turn.get("error") or {}
        decision = TurnDecision(
            route="refuse", readiness="unsupported", write_blocked=True,
            reason_code=str(error.get("code") or turn.get("halt") or "TURN_FAILED"),
        )
        return update_partition(state, "turn", decision=decision.model_dump(mode="json"))
    proposal = turn.get("parsed_proposal")

    snapshot = runtime.snapshot_for(state["session"].get("turn_mode", "active"))
    decision = evaluate_gate(snapshot, proposal, runtime.candidates)
    return update_partition(
        state,
        "turn",
        decision=decision.model_dump(mode="json"),
        halt=None,
        error=None,
    )


def route_after_decision(state: GraphState) -> str:
    """Read the already-written Decision, with no Proposal interpretation."""
    return route_from(TurnDecision.model_validate(state["turn"]["decision"]))


__all__ = [
    "Halt",
    "halt_update",
    "propose_round",
    "parse_validate",
    "decide_turn",
    "route_after_decision",
    "route_from",
    "timeout_error",
    "understand",
    "understanding_error",
]

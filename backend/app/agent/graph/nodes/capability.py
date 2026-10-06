"""Closed Keke capability choice before the semantic business proposal."""

from __future__ import annotations

import time
from typing import Any

from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, update_partition
from app.agent.graph.nodes.understand import halt_update, timeout_error
from app.llm.kev_provider import (
    CAPABILITY_CRITERIA,
    CAPABILITY_CRITERIA_VERSION,
    KevUnavailable,
    get_kev_provider,
)


def _capability_context(snapshot: Any) -> dict[str, Any]:
    return {
        "current_role": "keke",
        "selected_object": {
            "goal": snapshot.goal_candidate,
            "plan": snapshot.current_plan,
            "purchase_summary": snapshot.purchase_summary,
        },
        "recent_dialogue": list(snapshot.recent_messages[-6:]),
        "utterance": snapshot.message,
        "pending_question": snapshot.pending_clarification,
        "clarification_answer": snapshot.clarification_answer,
        "entry_context": snapshot.entry_context,
    }


def route_capability(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Select one Keke capability; this choice cannot author business semantics."""
    runtime = context_of(runtime)
    if runtime.stop():
        return halt_update(state, "stopped")
    if runtime.expired():
        return halt_update(state, "timed_out", timeout_error())

    snapshot = runtime.snapshot_for(state["session"].get("turn_mode", "active"))
    context = _capability_context(snapshot)
    call = {
        "call_number": 1,
        "stage": "capability",
        "model": "kev-latest",
        "repair": False,
        "read_result_count": 0,
        "remaining_budget_s": (
            round(runtime.remaining(), 3) if runtime.remaining() is not None else None
        ),
        "criteria_version": CAPABILITY_CRITERIA_VERSION,
        "criteria": CAPABILITY_CRITERIA,
        "input": context,
    }
    runtime.on_model_call({
        "call_number": call["call_number"],
        "stage": call["stage"],
        "model": call["model"],
        "status": "started",
        "criteria_version": call["criteria_version"],
    })
    started = time.monotonic()
    try:
        answer, raw = get_kev_provider().route_capability(context)
    except KevUnavailable:
        runtime.on_model_call(
            {
                **call,
                "status": "failed",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "code": "KEV_UNAVAILABLE",
            }
        )
        raise

    duration_ms = int((time.monotonic() - started) * 1000)
    clarification_answer = runtime.clarification_answer
    direct_product_type = bool(
        clarification_answer
        and clarification_answer["slot"] == "product_type"
    )
    runtime.on_model_call(
        {
            **call,
            "status": "completed",
            "duration_ms": duration_ms,
            "capability": answer.choice,
            "branch": (
                "direct_product_type_workflow"
                if direct_product_type
                else "semantic_understanding"
            ),
            "probabilities": answer.probabilities,
            "raw_response": raw,
        }
    )
    if runtime.stop():
        return halt_update(state, "stopped")
    if runtime.expired():
        return halt_update(state, "timed_out", timeout_error())
    workflow_branch = (
        "direct_product_type_workflow"
        if direct_product_type
        else "understand"
    )
    return update_partition(
        state,
        "turn",
        capability=answer.choice,
        workflow_branch=workflow_branch,
    )


def route_after_capability(state: GraphState) -> str:
    """Choose the verified direct workflow or the existing semantic stage."""
    if state["turn"].get("halt"):
        return "understand"
    return state["turn"]["workflow_branch"]


__all__ = ["route_after_capability", "route_capability"]

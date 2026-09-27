"""Response payloads, composed from real state. Pure functions, no database.

Every turn answers with the same shape, and that shape is derived from what was
actually persisted — never from what the model claimed. Keeping these here means
the workflow and the semantic service describe a turn identically instead of
drifting into two near-copies.

Nothing here reads a model, a session row or the database: it takes ``TaskState``
and returns a dict. The money and the item list are the plan's own values, so a
model-authored price can never reach the user through this path.
"""

from __future__ import annotations

from typing import Any

from app.agent.state import TaskState
from app.models.session import GuideSession

#: Statuses a client already understands. Anything else falls back to ``accepted``
#: rather than leaking an internal step name into the API contract.
KNOWN_ANSWER_STATUSES = frozenset(
    {
        "accepted",
        "explained",
        "clarifying",
        "failed",
        "cancelled",
        "awaiting_confirmation",
        "understanding",
        "degraded",
    }
)


def plan_ready_payload(
    state: TaskState | None,
    session: GuideSession | None = None,
) -> dict[str, Any]:
    """The committed plan, in the same shape the HTTP response exposes.

    ``plan.ready`` must carry what was *persisted* — the merged plan, its real
    version and the authoritative task/session versions — never the single
    target a tool call just built. Emitting the tool result here would make the
    client drop the items of every other target until the turn finished.
    """
    plan = getattr(state, "plan", None) or {}
    return {
        "plan_effect": "replace",
        "plan_id": plan.get("plan_id"),
        "plan_version": plan.get("plan_version"),
        "task_id": getattr(state, "task_id", None),
        "state_version": getattr(state, "state_version", None),
        "session_version": getattr(session, "session_version", None),
        "mode": plan.get("mode", "bundle"),
        "items": plan.get("items", []),
        "total_price_fen": plan.get("total_price_fen", 0),
        "selected_total_fen": plan.get("selected_total_fen"),
        "outstanding_total_fen": plan.get("outstanding_total_fen"),
        "expires_at": plan.get("expires_at"),
        "validation_status": plan.get("validation_status", "passed"),
        "coverage_mode": plan.get("coverage_mode"),
        "coverage_intent": plan.get("coverage_intent"),
        "uncovered_items": plan.get("uncovered_items", []),
        "gaps": plan.get("gaps", []),
        "can_confirm": plan.get("can_confirm"),
        "targets": plan.get("targets", []),
        "merged_sku_contributions": plan.get("merged_sku_contributions", []),
    }


def plan_people_note(
    plan: dict[str, Any],
    *,
    new_target: dict[str, Any] | None = None,
) -> str:
    """A headcount note belongs to a dish that was just prepared.

    Appending a drink or continuing a basket must not re-ask about people, and
    the note is never invented for a target the user did not just ask for.
    """
    source = new_target or {}
    if source.get("kind") != "dish":
        return ""
    # Headcount notes are never volunteered on the first list. The panel already
    # shows names, specs and quantities; explain the basis only when asked.
    return ""


def plan_summary_message(
    plan: dict[str, Any],
    *,
    new_group_ids: set[str] | None = None,
) -> str:
    """The authoritative, server-composed description of a real plan.

    Short and factual: how many products, the yuan subtotal and which targets are
    in the basket. The panel already shows the list, the prices and the controls,
    so no instruction is repeated here, and a headcount note is only offered for a
    dish group the turn really committed (``new_group_ids``, taken from the turn's
    own receipts) — never again when the shopper adds a drink.
    Money is shown in yuan only, and the model never authors this sentence, so an
    invented price cannot reach the user through it.
    """
    items = plan.get("items") or []
    total = plan.get("selected_total_fen")
    if total is None:
        total = plan.get("total_price_fen") or 0
    parts = [
        f"已整理 {len(items)} 件商品，选中合计 ¥{int(total) / 100:.2f}（演示价格）。"
    ]
    names = [str(t.get("name")) for t in plan.get("targets") or [] if t.get("name")]
    if names:
        parts.append("包含：" + "、".join(dict.fromkeys(names)) + "。")
    for target in plan.get("targets") or []:
        for note in target.get("notes") or []:
            parts.append(f"{note}")
    # D3: a partial plan must say what it cannot serve. The wording is composed
    # by the server (a gap carries it), never by the model's prose, and never
    # invents a quantity or a promise.
    for gap in plan.get("gaps") or []:
        message = str((gap or {}).get("message") or "").strip()
        if message and message not in parts:
            parts.append(message)
    committed = new_group_ids or set()
    notes = [
        plan_people_note(plan, new_target=target)
        for target in plan.get("targets") or []
        if str(target.get("group_id") or "") in committed
    ]
    # One sentence per distinct headcount: two dishes prepared at the same
    # default must not repeat it.
    for note in dict.fromkeys(note for note in notes if note):
        parts.append(note)
    return "".join(parts)


def build_response(
    state: TaskState | None,
    session: GuideSession,
    message: str,
    *,
    clarification: str | None = None,
    plan_effect: str | None = None,
    pending_clarification: dict[str, Any] | None = None,
    status_override: str | None = None,
    decision: Any = None,
) -> dict[str, Any]:
    """The response for a turn that has no task yet."""
    if state is None:
        return {
            "session_id": session.session_id,
            "task_id": None,
            "state_version": 0,
            "status": status_override or "understanding",
            "answer_status": status_override or "accepted",
            "purchase_step": "none",
            "message": message,
            "clarification": clarification,
            "plan": None,
            "plan_effect": plan_effect or "keep",
            "pending_clarification": pending_clarification,
            "missing_constraints": [],
            **_decision_echo(decision),
        }
    response = build_task_response(
        state,
        message,
        clarification,
        plan_effect=plan_effect,
        pending_clarification=pending_clarification,
        decision=decision,
    )
    if status_override:
        response["status"] = status_override
        response["answer_status"] = status_override
    return response


def _decision_echo(decision: Any) -> dict[str, Any]:
    """The read-only view of the gate's decision.

    It is derived from the server's own decision object, never from the model's
    prose, and it is informational: it grants nothing, and a client that ignores
    it still sees the real plan and the real receipts.
    """
    if decision is None:
        return {"route": None, "readiness": None, "missing_slots": []}
    route = getattr(decision, "route", None)
    mutation_action = getattr(decision, "mutation_action", None)
    if isinstance(decision, dict):
        route = decision.get("route")
        mutation_action = decision.get("mutation_action")
    # Keep the public response vocabulary stable while the graph uses one
    # unified mutation route internally.  This is the single compatibility
    # adapter; no downstream node branches on these legacy spellings.
    if route == "mutation":
        route = mutation_action
    elif route == "retrieve":
        route = "answer"
    return {
        "route": route,
        "readiness": getattr(decision, "readiness", None),
        "missing_slots": list(getattr(decision, "missing_slots", None) or []),
    }


def build_task_response(
    state: TaskState,
    message: str,
    clarification: str | None = None,
    *,
    plan_effect: str | None = None,
    pending_clarification: dict[str, Any] | None = None,
    decision: Any = None,
) -> dict[str, Any]:
    """The response for a turn on an existing task.

    ``plan`` is only exposed for an effect that really replaced it, and only from
    the plan the state actually holds.
    """
    plan = None
    effect = plan_effect
    if effect is None:
        if state.current_step == "awaiting_confirmation" and state.plan:
            effect = "replace"
        elif state.current_step == "cancelled":
            effect = "clear"
        else:
            effect = "keep"
    if (
        state.plan
        and state.current_step in ("awaiting_confirmation", "clarifying", "completed")
        and effect == "replace"
    ):
        plan = {
            "plan_id": state.plan["plan_id"],
            "plan_version": state.plan["plan_version"],
            "mode": state.plan["mode"],
            "items": state.plan["items"],
            "total_price_fen": state.plan["total_price_fen"],
            "selected_total_fen": state.plan.get("selected_total_fen"),
            "outstanding_total_fen": state.plan.get("outstanding_total_fen"),
            "expires_at": state.plan["expires_at"],
            "validation_status": state.plan["validation_status"],
            "coverage_mode": state.plan.get("coverage_mode"),
            "coverage_intent": state.plan.get("coverage_intent"),
            "uncovered_items": state.plan.get("uncovered_items", []),
            "gaps": state.plan.get("gaps", []),
            "can_confirm": state.plan.get("can_confirm"),
            "targets": state.plan.get("targets", []),
            "merged_sku_contributions": state.plan.get("merged_sku_contributions", []),
        }
        if state.plan.get("gap_fill"):
            plan["gap_fill"] = state.plan["gap_fill"]
    pending = pending_clarification or state.pending_clarification
    purchase_step = state.current_step if state.current_step != "clarifying" else "clarifying"
    if state.current_step == "completed":
        purchase_step = "completed"
    answer_status = state.current_step
    if answer_status not in KNOWN_ANSWER_STATUSES:
        answer_status = "accepted"
    return {
        "session_id": state.session_id,
        "task_id": state.task_id,
        "state_version": state.state_version,
        "status": state.current_step,
        "answer_status": answer_status,
        "purchase_step": purchase_step,
        "message": message,
        "clarification": clarification,
        "plan": plan,
        "plan_effect": effect,
        "pending_clarification": pending,
        "missing_constraints": state.missing_constraints,
        **_decision_echo(decision),
    }


__all__ = [
    "build_response",
    "build_task_response",
    "plan_people_note",
    "plan_ready_payload",
    "plan_summary_message",
]

"""``load_context``: the graph's first node, and the only reader of stored state.

On every HTTP request the node re-reads the real business state from the existing
session store: the task the session is working on (its real id, kind and name),
the current plan and version, the shopper's explicit requirements, the live
pending questions, the candidates the shopper was really shown, and a short window
of recent messages. Those values fill ``authoritative``/``candidate`` and the
turn's provider input.

It reads through the existing context module (:mod:`app.agent.context`) rather
than re-deriving dialogue state, so the graph and the rest of the application can
never disagree about "the pending questions" or "what was displayed". It never
reads or restores an execution cursor: a LangGraph checkpoint does not exist in
this design.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from app.agent import context as turn_context
from app.agent.context_resolver import ContextResolver
from app.agent.graph.runtime import TurnRuntime, context_of
from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services.session_actions import effective_status
from app.services.memory_service import MemoryService
from app.services.template_matcher import dish_display_name, get_template_by_id

#: Terminal task statuses. A turn on one of these still enters the graph (it is
#: a read-only conversation about a settled purchase); the final guard refuses a
#: business write later.
_TERMINAL_STATUSES = ("completed", "cancelled", "superseded")


def turn_mode_for(task: GuideTask | None) -> str:
    """Which of the three entries this turn is: taskless / active / completed.

    Derived from the stored task, never supplied by the caller.
    """
    if task is None:
        return "taskless"
    if effective_status(task) in _TERMINAL_STATUSES:
        return "completed"
    return "active"


def _real_target(
    db: Any, state: Any, plan: dict[str, Any] | None
) -> tuple[str | None, str | None, str | None]:
    """The real target the session is built on: kind, id and display name.

    A dish the task is actively built on wins; otherwise the plan's first target.
    The id is the server's own id, so a follow-up ("补人数", "第二个") attaches to
    the same real object without re-resolving it.
    """
    active_id = getattr(state, "active_template_id", None)
    if active_id:
        dish = get_template_by_id(db, str(active_id))
        name = dish_display_name(dish) if dish else str(active_id)
        return "dish", str(active_id), name
    for target in (plan or {}).get("targets") or []:
        target_id = target.get("target_id") or target.get("group_id")
        if target_id:
            return (
                str(target.get("kind") or "group"),
                str(target_id),
                str(target.get("name") or target_id),
            )
    return None, None, None


def _authoritative(
    db: Any,
    session: GuideSession,
    task: GuideTask | None,
    state: Any,
    pending: list[dict[str, Any]],
) -> dict[str, Any]:
    plan = json.loads(task.plan_json) if task and task.plan_json else None
    kind, target_id, target_name = _real_target(db, state, plan)
    return {
        "task_id": session.current_task_id,
        "plan_id": (plan or {}).get("plan_id"),
        "plan_version": (plan or {}).get("plan_version"),
        "state_version": task.state_version if task else 0,
        "session_version": session.session_version,
        "pending": list(pending),
        "target_kind": kind,
        "target_id": target_id,
        "target_name": target_name,
        "requirements": (
            state.requirements.to_dict() if state is not None and state.requirements else {}
        ),
    }


def _merge_constraints(
    base: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    """Union of read exclusions and the stricter budget, as plain requirements."""
    merged = dict(base or {})
    exclusions = list(
        dict.fromkeys(
            [
                *(merged.get("excluded_ingredients") or []),
                *(extra.get("excluded_ingredients") or []),
            ]
        )
    )
    if exclusions:
        merged["excluded_ingredients"] = exclusions
    budgets = [
        value
        for value in (merged.get("budget_fen"), extra.get("budget_fen"))
        if value is not None
    ]
    if budgets:
        merged["budget_fen"] = min(budgets)
    return merged


def build_turn_inputs(
    db: Any,
    *,
    owner_id: str,
    session: GuideSession,
    message: str,
    store_id: str | None = None,
    delivery_zone_id: str | None = None,
) -> dict[str, Any]:
    """Assemble one request's real business context and provider inputs.

    Separated from the node so the read itself is callable without a graph run.
    Nothing here writes.
    """
    ctx = ContextResolver(db, owner_id).resolve(session.session_id)
    store = store_id or getattr(ctx, "store_id", "") or "store-demo-01"
    zone = delivery_zone_id or getattr(ctx, "delivery_zone_id", "") or "zone-default"
    task = getattr(ctx, "task", None)
    state = getattr(ctx, "state", None)
    context = turn_context.load_context(db, session) or {}
    candidates = turn_context.build_candidate_set(
        db, store_id=store, delivery_zone_id=zone, state=state
    )
    turn_context.restore_displayed_references(
        db, candidates, context=context, store_id=store
    )
    task_id = getattr(state, "task_id", None)
    plan_version = getattr(state, "state_version", 0)
    focus_refs = turn_context.build_focus_refs(
        candidates,
        state=state,
        context=context,
        task_id=task_id,
        plan_version=plan_version,
    )
    goal_candidate = turn_context.goal_candidate_from_context(
        context, task_id=task_id, plan_version=plan_version
    )
    pending = turn_context.pending_for_session(db, session)
    displayed = list(context.get("displayed_candidates", []))
    snapshot = turn_context.build_turn_snapshot(
        turn_mode=turn_mode_for(task),
        message=message,
        candidates=candidates,
        state=state,
        ctx=ctx,
        context=context,
        focus_refs=focus_refs,
        goal_candidate=(goal_candidate.model_dump() if goal_candidate else None),
    )
    snapshot = replace(snapshot, memories=MemoryService(db, owner_id).recall(message))
    session_constraints = dict(context.get("session_constraints") or {})
    if session_constraints:
        snapshot = replace(
            snapshot,
            requirements=_merge_constraints(snapshot.requirements, session_constraints),
        )
    authoritative = _authoritative(db, session, task, state, pending)
    if session_constraints:
        authoritative["requirements"] = _merge_constraints(
            authoritative.get("requirements") or {}, session_constraints
        )
    return {
        "candidates": candidates,
        "snapshot": snapshot,
        "store_id": store,
        "delivery_zone_id": zone,
        "focus_refs": focus_refs,
        "goal_candidate": goal_candidate,
        "displayed": displayed,
        "pending": pending,
        "turn_mode": turn_mode_for(task),
        "authoritative": authoritative,
        "entry_anchor": {
            "task_id": session.current_task_id,
            "state_version": task.state_version if task else 0,
            "session_version": session.session_version,
        },
    }


def load_context(state: dict[str, Any], runtime: TurnRuntime) -> dict[str, Any]:
    """Fill ``authoritative``/``candidate`` for this request, or fail loudly.

    Authorization uses the same contract everywhere: a missing session and a
    session owned by someone else are both refused as ``SESSION_FORBIDDEN``.
    """
    runtime = context_of(runtime)
    session_id = state["session"]["session_id"]
    owner_id = state["session"].get("owner_id")
    if not owner_id:
        raise ValueError("OWNER_ID_REQUIRED: owner_id must be provided in session state")
    db = runtime.db
    if db is None:
        raise ValueError("DB_REQUIRED: the runtime context must carry a database session")

    db.expire_all()
    session = db.get(GuideSession, session_id)
    if session is None or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

    inputs = build_turn_inputs(
        db,
        owner_id=owner_id,
        session=session,
        message=str(state["turn"].get("user_input") or ""),
        store_id=runtime.store_id,
        delivery_zone_id=runtime.delivery_zone_id,
    )
    runtime.candidates = inputs["candidates"]
    snapshot = inputs["snapshot"]
    if runtime.view_context is not None:
        # The request's view is a pure input for this run; it is persisted by the
        # commit transaction, never written to the session before the turn runs.
        snapshot = replace(snapshot, view_context=dict(runtime.view_context))
    runtime.snapshot = snapshot
    runtime.store_id = inputs["store_id"]
    runtime.delivery_zone_id = inputs["delivery_zone_id"]
    runtime.entry_anchor = inputs["entry_anchor"]
    return {
        "session": {**state.get("session", {}), "turn_mode": inputs["turn_mode"]},
        "authoritative": inputs["authoritative"],
        "candidate": {
            "focus_refs": inputs["focus_refs"],
            "goal_candidate": inputs["goal_candidate"],
            "displayed_candidates": inputs["displayed"],
        },
    }


__all__ = ["build_turn_inputs", "load_context", "turn_mode_for"]

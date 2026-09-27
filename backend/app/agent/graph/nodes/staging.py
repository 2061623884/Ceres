"""Shared pure helpers for the ``mutation`` and ``answer`` nodes.

Nothing here writes: it computes the immutable turn facts, loads the task state
through the existing services, and turns a decided proposal into the durable
conversation-context plan the single commit transaction later applies. Kept in
its own module so ``mutation`` and ``answer`` share one implementation instead of
duplicating it.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app.agent import context as turn_context
from app.agent.graph.runtime import TurnRuntime
from app.agent.graph.state import GraphState, update_partition
from app.agent.protocol import SemanticProtocolError
from app.agent.state import TaskState
from app.agent.turn_context_plan import gate_pending, plan_context_writes
from app.schemas.goal import TurnDecision


def preconditions(state: GraphState, runtime: TurnRuntime | None = None) -> dict[str, Any]:
    """The immutable turn facts the stage and the final guard must defend.

    When ``load_context`` bound the request's entry anchor, it is authoritative:
    a later read — or a task changing terminal since — can never move it.
    """
    anchor = getattr(runtime, "entry_anchor", None) if runtime is not None else None
    if anchor:
        return {
            "session_id": state["session"]["session_id"],
            "task_id": anchor.get("task_id"),
            "state_version": int(anchor.get("state_version") or 0),
            "session_version": int(anchor.get("session_version") or 0),
        }
    return {
        "session_id": state["session"]["session_id"],
        "task_id": state["authoritative"].get("task_id"),
        "state_version": state["authoritative"].get("state_version", 0),
        "session_version": state["authoritative"].get("session_version", 0),
    }


def load_state(db: Any, session_id: str, owner_id: str) -> tuple[Any, TaskState | None]:
    from app.models.session import GuideSession, GuideTask

    session = db.get(GuideSession, session_id)
    if session is None or session.owner_id != owner_id:
        return session, None
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    if task is not None and task.owner_id != session.owner_id:
        task = None
    if task is None:
        return session, None
    return session, TaskState.from_db(task, entry_context={})


def base(state: GraphState, runtime: TurnRuntime, **fields: Any) -> dict[str, Any]:
    """A whole-partition ``staged`` update carrying the invariant turn facts."""
    return update_partition(
        state,
        "staged",
        preconditions=preconditions(state, runtime),
        **fields,
    )


def plan_context(
    state: GraphState,
    runtime: TurnRuntime,
    proposal: Any,
    decision: TurnDecision | None,
    *,
    committed_refs: set[Any] | None = None,
    activated: bool = False,
    business_pending: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Compute the durable conversation context (pure). The commit applies it."""
    if runtime.db is None:
        return None
    session, task_state = load_state(
        runtime.db, state["session"]["session_id"], runtime.owner_id
    )
    if session is None:
        return None
    context = turn_context.load_context(runtime.db, session) or {}
    try:
        new_pending = [
            turn_context.build_pending(u, runtime.candidates) for u in proposal.uncertainties
        ]
        gate_items = gate_pending(
            decision,
            proposal,
            runtime.candidates,
            conflict=None,
            focus_refs=(
                list(runtime.snapshot.focus_refs or []) if runtime.snapshot else []
            ),
        )
        action_results = (
            [
                {"status": "committed", "verb": "add", "candidate_ref": r}
                for r in (committed_refs or set())
            ]
            if activated
            else []
        )
        plan = plan_context_writes(
            context=context,
            session=session,
            proposal=proposal,
            candidates=runtime.candidates,
            decision=decision,
            state=task_state,
            previous_task_id=state["authoritative"].get("task_id"),
            action_results=action_results,
            gate_pending_items=gate_items,
            new_pending=new_pending,
            business_pending=list(business_pending or []),
        )
    except SemanticProtocolError as exc:
        return {
            "__error__": {
                "code": exc.code,
                "message": exc.message,
                "retryable": bool(exc.retryable),
            }
        }
    data = dataclasses.asdict(plan)
    data.pop("decision", None)
    return data


def anchor_for(state: GraphState, runtime: TurnRuntime) -> Any:
    from app.services.task_lifecycle_service import TurnAnchor

    pre = preconditions(state, runtime)
    return TurnAnchor(
        session_id=pre["session_id"],
        task_id=pre["task_id"],
        state_version=int(pre["state_version"] or 0),
    )


def mutation_payload(mutation: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    return asdict(mutation) if is_dataclass(mutation) else dict(mutation)


__all__ = [
    "anchor_for",
    "base",
    "load_state",
    "mutation_payload",
    "plan_context",
    "preconditions",
]

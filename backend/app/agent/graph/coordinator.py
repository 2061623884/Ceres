"""The Graph turn entry: one callable that runs one Guide request on the graph.

One HTTP request is one fresh graph run: ``START → load_context → understand →
{retrieve | mutation | answer} → answer → respond → END``. There is no
checkpoint, no run/thread/step binding and no resume command. Idempotency is
handled by the request-level receipt service **before** the graph starts: a
completed receipt replays with zero model calls and no business write, and the
same ``request_id`` replayed with a different body is always a conflict.

The reservation is taken in an independent transaction on the same engine as the
caller's session, so another connection can see it before the turn runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.agent.graph.graph import get_graph
from app.agent.graph.runtime import TurnRuntime
from app.agent.graph.state import initial_state
from app.agent.request_contract import request_digest, validate_preconditions
from app.agent.turn_primitives import LoopBudget
from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services.turn_receipt_service import TurnReceiptService


def _live_task(db: Any, session: GuideSession) -> GuideTask | None:
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    if task is not None and task.owner_id != session.owner_id:
        return None
    return task


def run_graph_turn(
    db: Any,
    *,
    owner_id: str,
    session_id: str,
    message: str,
    request_id: str,
    provider: Any,
    reads: Any,
    budget: LoopBudget | None = None,
    should_stop: Callable[[], bool] | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
    expected_task_id: str | None = None,
    expected_state_version: int | None = None,
    expected_session_version: int | None = None,
    view_context: dict[str, Any] | None = None,
    handoff_recent_messages: list[dict[str, Any]] | None = None,
    store_id: str | None = None,
    delivery_zone_id: str | None = None,
    trace_id: str | None = None,
    model_mode: str | None = None,
    business_data_mode: str | None = None,
    on_phase: Callable[[str], None] | None = None,
    on_model_call: Callable[[dict[str, Any]], None] | None = None,
    progress_sink: Any = None,
) -> dict[str, Any]:
    """Run one Graph turn and return its complete, committed HTTP response."""
    db.expire_all()
    session = db.get(GuideSession, session_id)
    if session is None or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

    digest = request_digest(
        message=message,
        expected_task_id=expected_task_id,
        expected_state_version=expected_state_version,
        expected_session_version=expected_session_version,
        view_context=view_context,
    )
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    receipts = TurnReceiptService(factory, owner_id)

    # 1) A committed receipt wins before any model call or business write.
    completed = receipts.lookup_completed(session_id, request_id, digest)
    if completed is not None:
        return completed

    # 2) Explicit client expectations are admission conditions: a stale request
    #    must not reserve a step or run the model.
    if (
        expected_task_id is not None
        or expected_state_version is not None
        or expected_session_version is not None
    ):
        validate_preconditions(
            session,
            _live_task(db, session),
            expected_task_id=expected_task_id,
            expected_state_version=expected_state_version,
            expected_session_version=expected_session_version,
        )

    reservation = receipts.reserve(
        session_id,
        request_id,
        digest,
        expected_task_id=expected_task_id,
    )
    if reservation.is_completed:
        return dict(reservation.completed_receipt or {})

    try:
        state = initial_state(
            session_id=session_id,
            owner_id=owner_id,
            turn_id=f"turn-{request_id}",
            user_input=message,
        )
        runtime = TurnRuntime(
            provider=provider,
            reads=reads,
            budget=budget or LoopBudget(),
            should_stop=should_stop or (lambda: False),
            deadline=deadline,
            **({"clock": clock} if clock is not None else {}),
            db=db,
            owner_id=owner_id,
            session_id=session_id,
            request_id=request_id,
            expected_task_id=expected_task_id,
            expected_state_version=expected_state_version,
            expected_session_version=expected_session_version,
            view_context=dict(view_context) if view_context else None,
            handoff_recent_messages=handoff_recent_messages,
            store_id=store_id or "store-demo-01",
            delivery_zone_id=delivery_zone_id or "zone-default",
            trace_id=trace_id,
            model_mode=model_mode,
            business_data_mode=business_data_mode,
            reservation=reservation,
            receipt_service=receipts,
            progress_sink=progress_sink,
        )
        if on_phase is not None:
            runtime.on_phase = on_phase
        if on_model_call is not None:
            runtime.on_model_call = on_model_call

        get_graph().invoke(state, context=runtime)
        return dict(runtime.response or {})
    except Exception as exc:
        db.rollback()
        receipts.fail(
            session_id,
            request_id,
            token=reservation.token,
            error=_failure_error(exc),
        )
        raise


def _failure_error(exc: Exception) -> dict[str, Any]:
    """The real business error of a failed request, preserved for its replay."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    retryable = getattr(exc, "retryable", None)
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        nested = detail["error"]
        code = code or nested.get("code")
        message = message or nested.get("message")
        if retryable is None:
            retryable = nested.get("retryable")
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = 502 if retryable else 400
    return {
        "code": str(code or type(exc).__name__),
        "message": str(message) if isinstance(message, str) else str(exc)[:200],
        "retryable": bool(retryable),
        "http_status": status,
    }


__all__ = ["run_graph_turn"]

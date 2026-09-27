"""Shared request identity and explicit-precondition checks.

The HTTP turn request carries the client's expectation of the task/state/session
versions it is acting on. ``GuideWorkflow.process_turn`` and the Graph
coordinator must interpret them identically, so both compute the idempotency
digest and validate the expectations here — one implementation, no drift.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.errors import AppError


def request_digest(
    *,
    message: str,
    expected_task_id: str | None,
    expected_state_version: int | None,
    expected_session_version: int | None,
    view_context: dict[str, Any] | None,
) -> str:
    """The exact digest the legacy workflow has always computed.

    Same JSON fields, same ``None`` handling, same ``sort_keys`` and the default
    ``ensure_ascii=True`` — so a receipt committed by either path replays under
    the other.
    """
    return hashlib.sha256(
        json.dumps(
            {
                "message": message,
                "expected_task_id": expected_task_id,
                "expected_state_version": expected_state_version,
                "expected_session_version": expected_session_version,
                "view_context": view_context,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def validate_preconditions(
    session: Any,
    task: Any,
    *,
    expected_task_id: str | None,
    expected_state_version: int | None,
    expected_session_version: int | None,
) -> None:
    """Refuse a request whose explicit expectations the live rows have outgrown.

    Mirrors ``GuideWorkflow.process_turn``: session version, then the task id /
    state version for an active task, the terminal-task case, and the taskless
    case where ``expected_task_id`` must be null.
    """
    if (
        expected_session_version is not None
        and expected_session_version != session.session_version
    ):
        raise AppError(
            409,
            "STALE_STATE",
            "Session version mismatch",
            session_version=session.session_version,
            current_task_id=session.current_task_id,
        )

    from app.services.session_actions import effective_status

    if task is None:
        if expected_task_id is not None:
            raise AppError(
                409,
                "STALE_STATE",
                "No active task; expected_task_id must be null",
                state_version=0,
            )
        return

    if effective_status(task) in ("completed", "cancelled", "superseded"):
        if expected_task_id and expected_task_id != task.task_id:
            raise AppError(
                409,
                "STALE_STATE",
                "Task ID mismatch",
                task_id=task.task_id,
                state_version=task.state_version,
            )
        return

    if expected_task_id and expected_task_id != task.task_id:
        raise AppError(
            409,
            "STALE_STATE",
            "Task ID mismatch",
            task_id=task.task_id,
            state_version=task.state_version,
        )
    if expected_task_id is None:
        raise AppError(
            409,
            "STALE_STATE",
            "expected_task_id required",
            task_id=task.task_id,
            state_version=task.state_version,
        )
    if expected_state_version is not None and expected_state_version != task.state_version:
        raise AppError(
            409,
            "STALE_STATE",
            "State version mismatch",
            task_id=task.task_id,
            state_version=task.state_version,
        )


__all__ = ["request_digest", "validate_preconditions"]

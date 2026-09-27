"""Shared offline test helpers (scripted providers, SSE parsing)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


def parse_sse_events(chunks: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in chunks.split("\n\n")
        if line.startswith("data:")
    ]


def _turn_body(
    message: str,
    previous: dict[str, Any] | None,
    *,
    request_id: str | None = None,
    view_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    body: dict[str, Any] = {
        "request_id": request_id or str(uuid.uuid4()),
        "message": message,
        "expected_task_id": previous.get("task_id"),
        "expected_state_version": previous.get("state_version", 0),
        "expected_session_version": previous.get("session_version"),
    }
    if view_context is not None:
        body["view_context"] = view_context
    return body


def stream_turn(
    client,
    session_id: str,
    message: str,
    previous: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    view_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """POST SSE turn; returns parsed events (terminal payload in turn.completed)."""
    body = _turn_body(
        message, previous, request_id=request_id, view_context=view_context
    )
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{session_id}/turns/stream",
        json=body,
    ) as resp:
        resp.raise_for_status()
        chunks = "".join(resp.iter_text())
    return parse_sse_events(chunks)


_ERROR_HTTP_STATUS = {
    "STALE_STATE": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "TURN_IN_PROGRESS": 409,
    "SESSION_FORBIDDEN": 403,
}


@dataclass
class TurnHTTPResponse:
    """SSE-backed stand-in for the removed JSON ``POST /turns``."""

    status_code: int
    _body: dict[str, Any] | None = None
    _error: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        if self.status_code >= 400 and self._error is not None:
            return {"error": self._error}
        return self._body or {}

    @property
    def text(self) -> str:
        return json.dumps(self.json(), ensure_ascii=False)


def _http_status_for_error(payload: dict[str, Any]) -> int:
    code = str(payload.get("code") or "TURN_FAILED")
    if code in _ERROR_HTTP_STATUS:
        return _ERROR_HTTP_STATUS[code]
    if payload.get("retryable"):
        return 502
    return 400


def post_turn(
    client,
    session_id: str,
    message: str,
    previous: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> TurnHTTPResponse:
    """Drop-in replacement for ``client.post(.../turns)`` using SSE terminal events."""
    del headers  # SSE entry ignores extra HTTP headers in tests
    events = stream_turn(
        client,
        session_id,
        message,
        previous,
        request_id=request_id,
        view_context=extra.get("view_context"),
    )
    for event in reversed(events):
        if event.get("type") == "turn.completed":
            return TurnHTTPResponse(200, _body=event.get("payload") or {})
        if event.get("type") == "turn.stopped":
            payload = dict(event.get("payload") or {})
            payload.setdefault("status", "stopped")
            payload.setdefault("answer_status", "stopped")
            return TurnHTTPResponse(200, _body=payload)
        if event.get("type") == "error":
            err = dict(event.get("payload") or {})
            return TurnHTTPResponse(
                _http_status_for_error(err),
                _error={
                    "code": err.get("code", "TURN_FAILED"),
                    "message": err.get("message", ""),
                    "retryable": bool(err.get("retryable")),
                },
            )
    raise AssertionError("SSE stream ended without a terminal event")


def send_turn(
    client,
    session_id: str,
    message: str,
    previous: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One SSE turn; returns turn.completed payload or raises on error/stop."""
    response = post_turn(
        client,
        session_id,
        message,
        previous,
        request_id=request_id,
        headers=headers,
        **extra,
    )
    if response.status_code >= 400:
        err = response.json()["error"]
        raise AssertionError(
            f"SSE error {err.get('code')}: {err.get('message')}"
        )
    return response.json()


def terminal_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the terminal business payload from parsed SSE events."""
    for event in reversed(events):
        if event.get("type") in {"turn.completed", "turn.stopped"}:
            return dict(event.get("payload") or {})
        if event.get("type") == "error":
            err = event.get("payload") or {}
            raise AssertionError(
                f"SSE error {err.get('code')}: {err.get('message')}"
            )
    raise AssertionError("SSE stream ended without a terminal event")


def create_session(client, *, page: str = "home", category_id: str | None = None) -> str:
    body: dict[str, Any] = {
        "entry_context": {
            "page": page,
            "store_id": "store-demo-01",
            "delivery_zone_id": "zone-default",
        }
    }
    if category_id:
        body["entry_context"]["category_id"] = category_id
    return client.post("/api/v1/guide/sessions", json=body).json()["session_id"]

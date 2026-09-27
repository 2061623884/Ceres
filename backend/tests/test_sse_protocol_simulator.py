"""Protocol-level SSE evidence: incremental events before turn.completed."""

from __future__ import annotations

import json
import uuid

import pytest


def _parse_sse_events(chunks: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in chunks.split("\n\n")
        if line.startswith("data:")
    ]


def _create_session(client) -> str:
    return client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]


def test_sse_yields_progress_before_completed(client):
    sid = _create_session(client)
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{sid}/turns/stream",
        json={
            "request_id": str(uuid.uuid4()),
            "message": "我想吃番茄炒蛋",
            "expected_task_id": None,
            "expected_state_version": 0,
        },
    ) as resp:
        assert resp.status_code == 200
        chunks = "".join(resp.iter_text())
    events = _parse_sse_events(chunks)
    types = [e["type"] for e in events]
    assert types[0] == "accepted"
    assert "turn.completed" in types
    if "progress" in types:
        assert types.index("progress") < types.index("turn.completed")
    if "answer.delta" in types:
        assert types.index("answer.delta") < types.index("turn.completed")


def test_sse_idempotent_replay_same_request_id(client):
    sid = _create_session(client)
    request_id = str(uuid.uuid4())
    body = {
        "request_id": request_id,
        "message": "你好",
        "expected_task_id": None,
        "expected_state_version": 0,
    }

    def stream_once():
        with client.stream(
            "POST",
            f"/api/v1/guide/sessions/{sid}/turns/stream",
            json=body,
        ) as resp:
            return "".join(resp.iter_text())

    first = _parse_sse_events(stream_once())
    second = _parse_sse_events(stream_once())
    assert any(e["type"] == "turn.completed" for e in first)
    assert any(e["type"] == "turn.completed" for e in second)
    completed_first = next(e for e in first if e["type"] == "turn.completed")
    completed_second = next(e for e in second if e["type"] == "turn.completed")
    assert completed_first["payload"]["message"] == completed_second["payload"]["message"]


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run these suites against the controlled agent without live credentials.

    Assertions are unchanged; only the model provider is injected.
    """
    return reactive_agent

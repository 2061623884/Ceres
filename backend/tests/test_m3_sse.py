"""M3 SSE turn streaming."""

from __future__ import annotations

import json
import queue
import threading
import uuid

import pytest

from app.services.turn_stream_service import TurnStreamService


def _sink_defaults(**overrides):
    base = {
        "run_id": "run-test",
        "session_id": "sess-test",
        "event_queue": queue.Queue(),
        "seq_holder": {"value": 0},
        "task_id_holder": {"task_id": None},
        "message_id_holder": {"message_id": None},
        "plan_effect_holder": {"plan_effect": "replace"},
        "stop_event": threading.Event(),
    }
    base.update(overrides)
    return base


def _drain_queue(event_queue: queue.Queue) -> list[dict]:
    items: list[dict] = []
    while True:
        try:
            item = event_queue.get_nowait()
            if item is not None:
                items.append(item)
        except queue.Empty:
            break
    return items


def _parse_sse_events(chunks: str) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in chunks.split("\n\n") if line.startswith("data:")]


def _create_session(client) -> str:
    return client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]


def test_turn_stream_returns_accepted_and_completed(client):
    sid = _create_session(client)
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{sid}/turns/stream",
        json={
            "request_id": str(uuid.uuid4()),
            "message": "你好",
            "expected_task_id": None,
            "expected_state_version": 0,
        },
    ) as resp:
        assert resp.status_code == 200
        chunks = "".join(resp.iter_text())
    events = _parse_sse_events(chunks)
    types = [e["type"] for e in events]
    assert "accepted" in types
    assert "turn.completed" in types or "error" in types
    for event in events:
        if event["type"] == "progress":
            assert event["payload"].get("mock") is not True


def test_sse_terminal_payload_has_stable_fields(client):
    from app.agent.graph.response_contract import TERMINAL_PAYLOAD_FIELDS

    sid = _create_session(client)
    events = _stream_turn(client, sid, "你好")
    completed = next(e for e in events if e["type"] == "turn.completed")
    payload = completed["payload"]
    for field in TERMINAL_PAYLOAD_FIELDS:
        assert field in payload, f"missing terminal field: {field}"
    assert payload.get("session_id") == sid


def test_clarification_supplement_continues_same_session(client, semantic_provider):
    """After a clarify turn, the next request continues on the same session."""
    from support.semantic_agent import Continuation

    def ask_which(request):
        rows = request["candidates"]["dishes"]
        assert rows, "the lookup really returned dishes"
        return {
            "reply": "你想吃哪一道？",
            "uncertainties": [
                {
                    "slot": "dish_choice",
                    "question": "你想吃哪一道？",
                    "options": [{"candidate_ref": r["ref"]} for r in rows[:2]],
                }
            ],
        }

    def pick_one(request):
        ref = request["candidates"]["dishes"][0]["ref"]
        return {
            "reply": "就这个",
            "mutations": [{"verb": "add", "candidate_ref": ref, "name": "番茄炒蛋"}],
        }

    provider = semantic_provider(
        [{"lookups": [{"kind": "dish", "query": "番茄"}]}, Continuation(ask_which), Continuation(pick_one)]
    )
    sid = _create_session(client)
    first = _stream_turn(client, sid, "我想吃个菜")
    first_payload = next(e["payload"] for e in first if e["type"] == "turn.completed")
    assert first_payload.get("pending_clarifications"), first_payload

    second = _stream_turn(client, sid, "第一个", first_payload)
    assert "turn.completed" in [e["type"] for e in second]
    second_payload = next(e["payload"] for e in second if e["type"] == "turn.completed")
    # Same session accepts a follow-up SSE turn after clarify (a new request on
    # the same business session, not a new session and not a graph resume).
    assert second_payload.get("session_id") == sid


def test_stream_sink_emits_real_phase_events(db_session):
    svc = TurnStreamService(db_session, "owner-test")
    kwargs = _sink_defaults()
    sink = svc._build_stream_sink(**kwargs)

    sink.on_phase("understanding")
    sink.on_phase("retrieve")
    sink.on_phase("validate")

    pending = _drain_queue(kwargs["event_queue"])
    assert [e["type"] for e in pending] == ["progress", "progress", "progress"]
    assert [e["payload"]["phase"] for e in pending] == ["understanding", "retrieve", "validate"]
    assert all(e["payload"].get("mock") is not True for e in pending)


def test_stream_plan_ready_only_from_sink_callback(db_session):
    svc = TurnStreamService(db_session, "owner-test")
    kwargs = _sink_defaults(seq_holder={"value": 1}, task_id_holder={"task_id": "task-1"}, message_id_holder={"message_id": "msg-1"}, plan_effect_holder={"plan_effect": "keep"})
    sink = svc._build_stream_sink(**kwargs)

    sink.on_plan_ready({"plan_id": "plan-1", "items": [], "plan_effect": "keep"})

    pending = _drain_queue(kwargs["event_queue"])
    assert len(pending) == 1
    event = pending[0]
    assert event["type"] == "plan.ready"
    assert event["payload"]["plan"]["plan_id"] == "plan-1"
    assert event["payload"]["plan_effect"] == "keep"


def test_stream_sink_rejects_invalid_phase(db_session):
    svc = TurnStreamService(db_session, "owner-test")
    sink = svc._build_stream_sink(**_sink_defaults())
    with pytest.raises(ValueError, match="invalid turn phase"):
        sink.on_phase("planning")


def test_stream_sink_emits_clarification_event(db_session):
    svc = TurnStreamService(db_session, "owner-test")
    kwargs = _sink_defaults()
    sink = svc._build_stream_sink(**kwargs)

    sink.on_clarification({"question": "几个人？"})

    pending = _drain_queue(kwargs["event_queue"])
    assert len(pending) == 1
    assert pending[0]["type"] == "clarification"
    assert pending[0]["payload"]["question"] == "几个人？"


_ALLOWED_PHASES = ("understanding", "retrieve", "validate")


def _assert_monotonic_sequences(events: list[dict]) -> None:
    sequences = [e["sequence"] for e in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def _assert_phase_order(phases: list[str]) -> None:
    order = [_ALLOWED_PHASES.index(p) for p in phases]
    assert order == sorted(order)


def _stream_turn(
    client,
    session_id: str,
    message: str,
    previous: dict | None = None,
) -> list[dict]:
    previous = previous or {}
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{session_id}/turns/stream",
        json={
            "request_id": str(uuid.uuid4()),
            "message": message,
            "expected_task_id": previous.get("task_id"),
            "expected_state_version": previous.get("state_version", 0),
            "expected_session_version": previous.get("session_version"),
        },
    ) as resp:
        assert resp.status_code == 200
        chunks = "".join(resp.iter_text())
    return _parse_sse_events(chunks)


def test_turn_stream_event_order_greeting(client):
    sid = _create_session(client)
    events = _stream_turn(client, sid, "你好")
    types = [e["type"] for e in events]

    assert types[0] == "accepted"
    assert events[0]["sequence"] == 0
    _assert_monotonic_sequences(events)
    assert types[-1] in {"turn.completed", "error"}
    if "turn.completed" in types:
        assert types.index("turn.completed") == len(types) - 1
    progress_indices = [i for i, t in enumerate(types) if t == "progress"]
    if progress_indices and "turn.completed" in types:
        assert max(progress_indices) < types.index("turn.completed")


def test_turn_stream_progress_phases_are_real_and_ordered(client):
    sid = _create_session(client)
    events = _stream_turn(client, sid, "我想吃番茄炒蛋")
    progress = [e for e in events if e["type"] == "progress"]

    assert progress, events
    phases = [e["payload"]["phase"] for e in progress]
    assert all(p in _ALLOWED_PHASES for p in phases)
    _assert_phase_order(phases)
    assert all(e["payload"].get("mock") is not True for e in progress)
    _assert_monotonic_sequences(events)


def test_turn_stream_plan_ready_before_completion(client):
    sid = _create_session(client)
    events = _stream_turn(client, sid, "我想吃番茄炒蛋")
    types = [e["type"] for e in events]
    assert "plan.ready" in types
    assert "turn.completed" in types
    assert types.index("plan.ready") < types.index("turn.completed")
    plan_event = next(e for e in events if e["type"] == "plan.ready")
    completed = next(e for e in events if e["type"] == "turn.completed")
    assert plan_event["sequence"] < completed["sequence"]
    assert plan_event["payload"]["plan"]["plan_id"]
    # The event carries what was persisted, not a preview: the committed plan is
    # already the one the session snapshot reports, at the same state version.
    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session["plan"]["plan_id"] == plan_event["payload"]["plan"]["plan_id"]
    assert session["state_version"] == plan_event["payload"]["plan"]["state_version"]


def test_turn_stream_clarification_never_advertises_a_plan(client, semantic_provider):
    """A question-only turn commits no plan, so it must not emit ``plan.ready``.

    ``plan.ready`` is published from the commit path, after the state change is
    persisted. A turn that only asks which dish to cook has nothing committed and
    must deliver the question (before completion) without inventing a plan.
    """
    from support.semantic_agent import Continuation

    def ask_which(request):
        rows = request["candidates"]["dishes"]
        assert rows, "the lookup really returned dishes"
        return {
            "reply": "你想吃哪一道？",
            "uncertainties": [
                {
                    "slot": "dish_choice",
                    "question": "你想吃哪一道？",
                    "options": [{"candidate_ref": r["ref"]} for r in rows[:2]],
                }
            ],
        }

    semantic_provider(
        [{"lookups": [{"kind": "dish", "query": "番茄"}]}, Continuation(ask_which)]
    )

    sid = _create_session(client)
    events = _stream_turn(client, sid, "我想吃个菜")
    types = [e["type"] for e in events]
    assert "clarification" in types, events
    assert "plan.ready" not in types, events
    assert types[-1] == "turn.completed", types
    assert types.index("clarification") < types.index("turn.completed")
    _assert_monotonic_sequences(events)

    # Nothing was committed: the session still has no plan to show.
    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session["plan"] is None, session


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run these suites against the controlled agent without live credentials.

    Assertions are unchanged; only the model provider is injected.
    """
    return reactive_agent

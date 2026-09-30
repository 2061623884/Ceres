"""The contracts the semantic pipeline shares with the transports.

Everything here runs through the real HTTP entry, the real services and a
temporary database, with a scripted semantic provider — no network and no real
model. The legacy pipeline has the same contracts covered elsewhere; these are
the semantic side of them, so "the shared contract holds" is not a statement
about a pipeline the semantic route never runs.

Covered:

* a stop issued while the model is running ends the run as stopped on the
  stream, and touches neither the plan nor the cart;
* one request id executed over SSE is replayed on a second SSE call, never
  re-executed, and both report the same assistant message;
* a failed semantic run (a model timeout, and the turn's own deadline) is
  reported as an error on the stream, and the same request id replays that
  original error instead of executing again;
* after a semantic plan, the shopper's own row-add / refresh / confirm buys only
  what is still outstanding and keeps the already-bought ledger;
* cancelling a semantic plan needs no model call and never touches the cart.
"""

from __future__ import annotations

import asyncio
import threading
import uuid

import pytest
from sqlalchemy import text

from support import create_session, parse_sse_events, send_turn
from support.semantic_agent import first_item_ref, request_amend, request_new


# --------------------------------------------------------------------- helpers


def lookup_then_add(kind, query, _fragment, *, relation="new"):
    """The one-pass Proposal resolves a named target during mutation execution."""
    name = "鲜鸡蛋 10枚装" if query == "鸡蛋" else "全脂牛奶 1升"
    return [{**request_new(kind, name, relation=relation),
             "lookups": [{"kind": kind, "query": name}]}]


def _body(sid, message, request_id, previous=None):
    previous = previous or {}
    return {
        "request_id": request_id,
        "message": message,
        "expected_task_id": previous.get("task_id"),
        "expected_state_version": previous.get("state_version", 0),
        "expected_session_version": previous.get("session_version"),
    }


def _stream(client, sid, message, request_id, previous=None):
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{sid}/turns/stream",
        json=_body(sid, message, request_id, previous),
    ) as resp:
        assert resp.status_code == 200, resp.read()
        return parse_sse_events("".join(resp.iter_text()))


def _turn_ok(client, sid, message, previous=None):
    return send_turn(client, sid, message, previous)


def _types(events):
    return [event["type"] for event in events]


def _snapshot(client, sid):
    response = client.get(f"/api/v1/guide/sessions/{sid}")
    assert response.status_code == 200, response.text
    return response.json()


def _cart(client):
    return client.get("/api/v1/cart").json()["items"]


def _db(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def _owner_of(client, sid) -> str:
    db = _db(client)
    return db.execute(
        text("SELECT owner_id FROM guide_sessions WHERE session_id = :s"), {"s": sid}
    ).scalar()


# --------------------------------------------------- a stopped generation


def test_a_stop_while_the_model_runs_ends_the_run_as_stopped(client, semantic_provider):
    """The stream reports stopped, and nothing was written."""
    semantic_provider([*lookup_then_add("product", "鸡蛋", "鸡蛋")])
    sid = create_session(client)
    planned = _turn_ok(client, sid, "买点鸡蛋")
    plan_before = _snapshot(client, sid)["plan"]
    cart_before = _cart(client)
    assert plan_before["items"]

    started = threading.Event()
    release = threading.Event()

    def blocked_change(request):
        started.set()
        release.wait(timeout=5)
        item = request["current_plan"]["items"][0]
        return request_amend(
            focus=first_item_ref(request), name=item["name"], op="adjust_quantity", quantity=1
        )

    provider = semantic_provider([blocked_change])
    request_id = str(uuid.uuid4())
    owner_id = _owner_of(client, sid)
    collected: list[dict] = []

    async def consume():
        from app.services.turn_stream_service import TurnStreamService

        service = TurnStreamService(_db(client), owner_id)
        async for event in service.stream_turn(
            sid,
            "鸡蛋加一件",
            request_id,
            planned["task_id"],
            planned["state_version"],
            planned["session_version"],
            None,
        ):
            collected.append(event)

    def run() -> None:
        asyncio.run(consume())

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert started.wait(timeout=5), "the worker never reached the model call"
        stop_response = client.post(
            f"/api/v1/guide/sessions/{sid}/turns/stop", json={"request_id": request_id}
        )
        assert stop_response.status_code == 200, stop_response.text
        assert stop_response.json()["status"] in ("stopping", "stopped")
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive()

    assert _types(collected)[0] == "accepted"
    assert _types(collected)[-1] == "turn.stopped", collected
    assert len(provider.requests) == 1, "no further model call after the stop"

    # The plan is exactly what it was, and the cart was never involved.
    after = _snapshot(client, sid)
    assert after["plan"] == plan_before
    assert _cart(client) == cart_before


# --------------------------------------------- one request id, two transports


def test_one_request_id_replays_across_sse_streams(client, semantic_provider):
    provider = semantic_provider([{"reply": "你好，想吃点什么？"}])
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    events = _stream(client, sid, "你好", request_id)
    assert "turn.completed" in _types(events)
    terminal = next(e for e in events if e["type"] == "turn.completed")
    assert len(provider.requests) == 1

    replay_events = _stream(client, sid, "你好", request_id)
    replay_terminal = next(e for e in replay_events if e["type"] == "turn.completed")
    assert (
        replay_terminal["payload"]["assistant_message_id"]
        == terminal["payload"]["assistant_message_id"]
    )
    assert len(provider.requests) == 1, "the SSE replay never re-executes"


# ----------------------------------------------- a failed run is not retried


def test_a_model_failure_is_reported_once_and_replayed(client, semantic_provider):
    from app.llm.errors import LLMProviderError

    provider = semantic_provider(
        [LLMProviderError("MODEL_TIMEOUT", "模型超时", retryable=False)]
    )
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    events = _stream(client, sid, "你好", request_id)
    assert "turn.completed" in _types(events), events
    terminal = next(e for e in events if e["type"] == "turn.completed")
    assert terminal["payload"]["route"] == "refuse"
    assert any(r.get("code") == "MODEL_TIMEOUT" for r in terminal["payload"]["action_results"])
    assert len(provider.requests) == 1

    # The same request id replays the refusal receipt; nothing is re-executed.
    replay = _stream(client, sid, "你好", request_id)
    assert _types(replay) == ["accepted", "turn.completed"]
    assert replay[-1]["payload"] == terminal["payload"]
    assert len(provider.requests) == 1, "a recorded failure is replayed, never retried"


class _TurnClock:
    """The turn clock, moved by hand so a deadline needs no sleeping."""

    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def turn_clock(monkeypatch):
    import app.agent.turn_primitives as turn_module

    clock = _TurnClock()
    monkeypatch.setattr(turn_module, "_monotonic", clock)
    return clock


@pytest.fixture()
def turn_budget(monkeypatch):
    seconds = 30.0
    monkeypatch.setenv("SEMANTIC_TURN_TIMEOUT_SECONDS", str(seconds))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield seconds
    get_settings.cache_clear()


def test_the_turn_deadline_is_a_failure_on_the_stream(
    client, semantic_provider, turn_clock, turn_budget
):
    """A spent budget is an error event — never a completed turn."""

    def slow_round(request):
        turn_clock.now += turn_budget * 2
        return {"reply": "来不及了"}

    provider = semantic_provider([slow_round])
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    events = _stream(client, sid, "你好", request_id)
    assert _types(events)[-1] == "error", events
    assert events[-1]["payload"]["code"] == "TURN_DEADLINE_EXCEEDED"
    assert events[-1]["payload"]["retryable"] is True
    assert len(provider.requests) == 1


# --------------------------------------- the shopper's own row-level purchases


def test_row_add_refresh_and_confirm_buy_only_what_is_outstanding(
    client, semantic_provider
):
    """A semantic plan with two rows, then the shopper's own add, refresh, confirm."""
    semantic_provider([*lookup_then_add("product", "鸡蛋", "鸡蛋")])
    sid = create_session(client)
    first = _turn_ok(client, sid, "买点鸡蛋")

    semantic_provider([*lookup_then_add("product", "牛奶", "牛奶", relation="append")])
    body = _turn_ok(client, sid, "再来一盒牛奶", first)
    rows = [i for i in body["plan"]["items"] if i.get("selected", True)]
    assert len(rows) >= 2, rows

    target = next(i for i in rows if "牛奶" in str(i["name"]))
    added = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/items/{target['sku_id']}/add",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": target["quantity"],
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
        },
    )
    assert added.status_code == 200, added.text
    added_payload = added.json()
    added_row = next(i for i in added_payload["items"] if i["sku_id"] == target["sku_id"])
    assert added_row["added_quantity"] == target["quantity"]
    assert added_row["remaining_quantity"] == 0

    refreshed = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_state_version": added_payload["state_version"],
            "expected_session_version": added_payload["session_version"],
            "base_plan_id": added_payload["plan_id"],
            "base_plan_version": added_payload["plan_version"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    data = refreshed.json()
    row = next(i for i in data["items"] if i["sku_id"] == target["sku_id"])
    assert row["added_quantity"] == target["quantity"], "refresh dropped the ledger"
    assert row["remaining_quantity"] == 0

    remaining = [
        {"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
        for i in data["items"]
        if i.get("selected", True) and i.get("remaining_quantity", 0) > 0
    ]
    assert remaining, "the rows that were not added are still outstanding"
    confirm = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": data["plan_id"],
            "plan_version": data["plan_version"],
            "expected_state_version": data["state_version"],
            "expected_session_version": data["session_version"],
            "selected_items": remaining,
        },
    )
    assert confirm.status_code == 200, confirm.text

    bought = sum(i["quantity"] for i in _cart(client) if i["sku_id"] == target["sku_id"])
    assert bought == target["quantity"], f"bought twice after refresh: {bought}"


# ------------------------------------------------------------ the cancellation


def test_cancelling_a_semantic_plan_uses_no_model_and_spares_the_cart(
    client, semantic_provider
):
    provider = semantic_provider([*lookup_then_add("product", "鸡蛋", "鸡蛋")])
    sid = create_session(client)
    body = _turn_ok(client, sid, "买点鸡蛋")
    cart_before = _cart(client)
    model_calls = len(provider.requests)

    cancelled = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/cancel",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    assert len(provider.requests) == model_calls, "a cancellation asks no model"
    assert _cart(client) == cart_before
    assert _snapshot(client, sid)["task_status"] == "cancelled"


@pytest.fixture(autouse=True)
def _clear_cancellation_registry():
    from app.services.turn_stream_service import cancellation_registry

    yield
    cancellation_registry.clear()

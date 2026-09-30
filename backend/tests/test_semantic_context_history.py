"""Cutover regressions: navigation reaches the model; every new plan has history."""

import json
import uuid

from app.models.conversation import GuideMessage, PlanSnapshot
from support import create_session, post_turn
from support.semantic_agent import request_new, reply_only


def _turn(client, sid, message, previous=None, **extra):
    previous = previous or {}
    response = post_turn(client, sid, message, previous, **extra)
    assert response.status_code == 200, response.text
    return response.json()


def _assert_snapshot(sid, body):
    from app.core import database

    plan = body["plan"]
    with database.SessionLocal() as db:
        snap = db.get(PlanSnapshot, (plan["plan_id"], plan["plan_version"]))
        assert snap is not None, "a plan_ref must resolve to immutable history"
        assert snap.session_id == sid
        assert snap.task_id == body["task_id"]
        stored = json.loads(snap.plan_json)
        assert [(r["sku_id"], r["quantity"]) for r in stored["items"]] == [
            (r["sku_id"], r["quantity"]) for r in plan["items"]
        ]
        msg = db.get(GuideMessage, body["assistant_message_id"])
        assert (msg.plan_id, msg.plan_version) == (snap.plan_id, snap.plan_version)
        return snap.plan_json


def test_first_and_post_terminal_purchases_have_immutable_snapshots(client, semantic_provider):
    semantic_provider([{
        **request_new("product", "鲜鸡蛋 10枚装"),
        "lookups": [{"kind": "product", "query": "鲜鸡蛋 10枚装"}],
    }])
    sid = create_session(client)
    first = _turn(client, sid, "买鸡蛋")
    first_history = _assert_snapshot(sid, first)

    cancelled = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/cancel",
        json={"request_id": str(uuid.uuid4()),
              "expected_session_version": first["session_version"],
              "expected_state_version": first["state_version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    previous = client.get(f"/api/v1/guide/sessions/{sid}").json()
    semantic_provider([{
        **request_new("product", "可乐 330毫升"),
        "lookups": [{"kind": "product", "query": "可乐 330毫升"}],
    }])
    second = _turn(client, sid, "另买可乐", previous)
    assert second["task_id"] != first["task_id"]
    _assert_snapshot(sid, second)
    assert _assert_snapshot(sid, first) == first_history
    assert client.get("/api/v1/cart").json()["items"] == []


def test_current_view_is_forwarded_and_persisted_without_overriding_supply(client, semantic_provider):
    provider = semantic_provider([reply_only("先看看。"), reply_only("还在看这个商品。")])
    sid = create_session(client, page="home")
    view = {"page": "product", "product_id": "demo:eggs-10", "category_id": None}
    first = _turn(client, sid, "这个呢", view_context=view)
    _turn(client, sid, "再看看", first)
    for request in provider.requests:
        assert request["view_context"] == view
        assert request["entry_context"]["page"] == "home"
        assert request["entry_context"]["store_id"] == "store-demo-01"
        assert request["entry_context"]["delivery_zone_id"] == "zone-default"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_view_context_is_a_pure_request_input_persisted_in_commit(client, semantic_provider):
    """The request's view never dirties the session before admission.

    It reaches the model as a pure input for this run, is persisted inside the
    commit transaction, is read back by a later turn that carries no view, and a
    replay of the same request returns the same receipt with no extra model call.
    """
    import uuid as _uuid

    provider = semantic_provider([reply_only("先看看。"), reply_only("还在看这个商品。")])
    sid = create_session(client, page="home")
    view = {"page": "product", "product_id": "demo:eggs-10", "category_id": None}
    request_id = str(_uuid.uuid4())

    first = post_turn(client, sid, "这个呢", request_id=request_id, view_context=view)
    assert first.status_code == 200, first.text
    body = first.json()
    assert provider.requests[0]["view_context"] == view
    assert provider.requests[0]["entry_context"]["page"] == "home"

    # A later turn without a view context still sees the persisted one.
    _turn(client, sid, "再看看", body)
    assert provider.requests[-1]["view_context"] == view

    # A replay of the same request returns the committed receipt without a call.
    calls_before = len(provider.requests)
    replay = post_turn(client, sid, "这个呢", request_id=request_id, view_context=view)
    assert replay.status_code == 200, replay.text
    assert replay.json()["message"] == body["message"]
    assert len(provider.requests) == calls_before
    assert client.get("/api/v1/cart").json()["items"] == []

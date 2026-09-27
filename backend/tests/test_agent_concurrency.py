"""What a turn may write when the shopper moved while the model was thinking.

A model call is slow. In that window the shopper can edit the plan through the
plan editor, confirm it, or start another task — all through their own requests,
on their own connection. A turn snapshotted the session before the call, so it
must refuse to write once the live session has moved on, and it must say so
instead of overwriting the edit or re-adding something already handled.

The user's side of each race is performed with **real services on a separate
SQLAlchemy session** against the same file-backed SQLite database, which is what
a second request would do. All model calls are scripted.
"""

from __future__ import annotations

import uuid

import pytest

from support import create_session, post_turn
from support.semantic_agent import (
    request_new,
    first_item_ref,
)


def send(client, sid, text, previous=None):
    previous = previous or {}
    return post_turn(client, sid, text, previous, request_id=str(uuid.uuid4()))


def send_ok(client, sid, text, previous=None):
    response = send(client, sid, text, previous)
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(client, sid):
    response = client.get(f"/api/v1/guide/sessions/{sid}")
    assert response.status_code == 200, response.text
    return response.json()


def cart_items(client):
    return client.get("/api/v1/cart").json()["items"]


def as_another_request(test_db_url, work):
    """Run ``work`` on its own engine, as a second request would.

    The engine is disposed afterwards: the test database is one file, and a
    pooled connection left open would keep the turn's own writes locked out.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    try:
        with Session(engine) as db:
            result = work(db)
            db.commit()
        return result
    finally:
        engine.dispose()


def add_named_product(name_fragment: str):
    """Name the requested product and let mutation resolve its real lookup."""

    def build(request):
        return named_product(request, name_fragment)

    return [build]


def named_product(request, name):
    name = {
        "鸡蛋": "鲜鸡蛋 10枚装",
        "可乐": "可乐 330毫升",
        "牛奶": "全脂牛奶 1升",
    }.get(name, name)
    return {
        "understanding": request_new(
            "product", name,
            relation="append" if request.get("current_plan") else "new",
        ),
        "lookups": [{"kind": "product", "query": name}],
    }


def test_a_plan_edited_while_the_model_runs_is_not_overwritten(
    client, semantic_provider, test_db_url
):
    """The shopper edits the plan mid-turn; the model's older add must be refused."""
    from app.agent.state import TaskState
    from app.models.session import GuideSession, GuideTask

    sid = create_session(client)
    cart_before = cart_items(client)

    def edit_the_plan_then_answer(request):
        # The shopper's own edit, on their own connection, while the model runs.
        def work(db):
            task = db.get(GuideTask, task_id)
            session = db.get(GuideSession, sid)
            state = TaskState.from_db(
                task, {"store_id": "store-demo-01", "delivery_zone_id": "zone-default"}
            )
            current = int(task.state_version)
            state.state_version = current + 1
            state.to_db(db, expected_version=current)
            session.session_version += 1

        as_another_request(test_db_url, work)

        return named_product(request, "可乐")

    semantic_provider(
        [
            *add_named_product("鸡蛋"),
            edit_the_plan_then_answer,
        ]
    )
    first = send_ok(client, sid, "买点鸡蛋", None)
    task_id = first["task_id"]
    before = snapshot(client, sid)
    response = send(client, sid, "再来一瓶可乐", before)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_STATE", response.json()

    # The user's edit stands; nothing was added on top of it; the cart is untouched.
    after = snapshot(client, sid)
    assert after["state_version"] != before["state_version"]
    assert [i["sku_id"] for i in after["plan"]["items"]] == [
        i["sku_id"] for i in before["plan"]["items"]
    ]
    assert cart_items(client) == cart_before


def test_a_task_opened_while_a_taskless_turn_was_thinking_is_not_taken_over(
    client, semantic_provider, test_db_url
):
    """A taskless turn may not claim a session another request has opened a task for."""
    from app.agent.state import Requirements, TaskState, new_task_id
    from app.models.session import GuideSession

    sid = create_session(client)
    cart_before = cart_items(client)

    def another_request_opens_a_task(request):
        def work(db):
            session = db.get(GuideSession, sid)
            state = TaskState(
                session_id=sid,
                task_id=new_task_id(),
                owner_id=session.owner_id,
                state_version=1,
                intent="purchase_task",
                entry_context={"store_id": "store-demo-01", "delivery_zone_id": "zone-default"},
                requirements=Requirements(),
                current_step="understanding",
            )
            state.to_db(db)
            session.current_task_id = state.task_id
            session.session_version += 1

        as_another_request(test_db_url, work)

        return named_product(request, "鸡蛋")

    semantic_provider([another_request_opens_a_task])
    response = send(client, sid, "买点鸡蛋")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_STATE", response.json()

    # The other request's task is the session's task, and it was not overwritten.
    live = snapshot(client, sid)
    assert live["task_id"] is not None
    assert live["plan"] is None, "the rejected turn must not have written a plan"
    assert cart_items(client) == cart_before


def test_a_supply_change_while_the_model_runs_is_not_overwritten(
    client, semantic_provider
):
    """A zone change invalidates the plan; a turn that snapshotted it may not write.

    The shopper's side is a real call to the existing supply-context endpoint, in
    the window where the model is still thinking.
    """
    semantic_provider([*add_named_product("鸡蛋")])
    sid = create_session(client)
    first = send_ok(client, sid, "买点鸡蛋", None)
    before = snapshot(client, sid)
    cart_before = cart_items(client)
    assert before["plan"]["items"]

    def switch_zone_then_answer(request):
        # The shopper changes the delivery zone through their own request.
        switched = client.post(
            f"/api/v1/guide/sessions/{sid}/supply-context",
            json={
                "request_id": str(uuid.uuid4()),
                "expected_session_version": before["session_version"],
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-other",
            },
        )
        assert switched.status_code == 200, switched.text

        return named_product(request, "可乐")

    semantic_provider([switch_zone_then_answer])
    response = send(client, sid, "再来一瓶可乐", before)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_STATE", response.json()

    # The invalidation stands, the plan is exactly what it was, and the cart is
    # untouched: the older proposal wrote nothing at all.
    after = snapshot(client, sid)
    assert after["plan"]["validation_status"] == "stale_supply", after["plan"]
    assert [i["sku_id"] for i in after["plan"]["items"]] == [
        i["sku_id"] for i in before["plan"]["items"]
    ]
    assert cart_items(client) == cart_before


def test_a_turn_that_nothing_touched_still_writes_normally(client, semantic_provider):
    """The guard must not turn an ordinary turn into a refusal."""
    semantic_provider([*add_named_product("鸡蛋")])
    sid = create_session(client)
    body = send_ok(client, sid, "买点鸡蛋")
    assert body["plan_effect"] == "replace"
    assert body["plan"] and body["plan"]["items"]


def test_a_same_task_turn_cannot_change_a_row_and_add_another(
    client, semantic_provider
):
    """A row edit plus a new goal is one compound batch: refused, unapplied."""
    semantic_provider([*add_named_product("鸡蛋")])
    sid = create_session(client)
    first = send_ok(client, sid, "买点鸡蛋", None)

    def change_then_add(request):
        item_ref = first_item_ref(request)
        item = request["current_plan"]["items"][0]
        return {
            "understanding": request_new("product", "全脂牛奶 1升", relation="append"),
            "lookups": [{"kind": "product", "query": "全脂牛奶 1升"}],
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": item_ref,
                    "name": item["name"],
                    "field": "quantity",
                    "quantity": {"mode": "delta", "value": 1},
                },
                {"verb": "add", "name": "全脂牛奶 1升"},
            ],
        }

    semantic_provider([change_then_add])
    body = send_ok(client, sid, "鸡蛋加一件，再来一盒牛奶", first)

    assert not [
        r for r in body["action_results"] if r.get("status") == "committed"
    ], body["action_results"]
    assert body["state_version"] == first["state_version"]
    assert body["task_id"] == first["task_id"]

    stored = snapshot(client, sid)
    assert stored["task_id"] == first["task_id"]
    eggs = [i for i in stored["plan"]["items"] if "鸡蛋" in str(i["name"])]
    assert eggs and eggs[0]["quantity"] == 1, stored["plan"]["items"]
    assert not any("牛奶" in str(i["name"]) for i in stored["plan"]["items"])



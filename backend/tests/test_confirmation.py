"""O01 confirmation and cart integration tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import database as db_module
from app.models.session import GuideTask
from support import post_turn


def _session(client, **entry_overrides):
    entry = {
        "page": "home",
        "category_id": None,
        "store_id": "store-demo-01",
        "delivery_zone_id": "zone-default",
    }
    entry.update(entry_overrides)
    resp = client.post("/api/v1/guide/sessions", json={"entry_context": entry})
    return resp.json()["session_id"]


def _turn(client, session_id, message, task_id=None, version=0):
    return post_turn(client, session_id, message, None, request_id=str(uuid.uuid4()))


def _awaiting_tomato_egg(client):
    sid = _session(client)
    turn = _turn(client, sid, "我想吃番茄炒蛋")
    assert turn.status_code == 200
    body = turn.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["plan"] is not None
    return body


def _confirm(client, task_id, plan, state_version, idempotency_key=None, selected_items=None):
    payload = {
        "plan_id": plan["plan_id"],
        "plan_version": plan["plan_version"],
        "expected_state_version": state_version,
        "selected_items": selected_items
        or [
            {"sku_id": item["sku_id"], "quantity": item["quantity"]}
            for item in plan["items"]
            if item.get("role", "required") == "required"
        ],
    }
    headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}
    return client.post(
        f"/api/v1/guide/tasks/{task_id}/confirm",
        json=payload,
        headers=headers,
    )


def _cart_qty(client, sku_id: str) -> int:
    cart = client.get("/api/v1/cart").json()
    for item in cart["items"]:
        if item["sku_id"] == sku_id:
            return item["quantity"]
    return 0


def test_confirm_writes_cart(client):
    body = _awaiting_tomato_egg(client)
    plan = body["plan"]
    skus = {
        item["sku_id"]
        for item in plan["items"]
        if item.get("role", "required") == "required"
    }

    confirm = _confirm(client, body["task_id"], plan, body["state_version"])
    assert confirm.status_code == 200, confirm.text

    cart = client.get("/api/v1/cart").json()
    cart_skus = {item["sku_id"] for item in cart["items"]}
    assert skus.issubset(cart_skus)
    assert cart["total_price_fen"] > 0


def test_confirm_idempotent_replay_does_not_double_qty(client):
    body = _awaiting_tomato_egg(client)
    plan = body["plan"]
    key = f"idem-{uuid.uuid4()}"
    version = body["state_version"]
    first = _confirm(client, body["task_id"], plan, version, idempotency_key=key)
    assert first.status_code == 200

    cart_after_first = client.get("/api/v1/cart").json()
    totals_first = {item["sku_id"]: item["quantity"] for item in cart_after_first["items"]}

    for _ in range(10):
        replay = _confirm(
            client,
            body["task_id"],
            plan,
            version,
            idempotency_key=key,
        )
        assert replay.status_code == 200
        assert replay.json()["confirmation_id"] == first.json()["confirmation_id"]

    cart_after_replay = client.get("/api/v1/cart").json()
    totals_replay = {item["sku_id"]: item["quantity"] for item in cart_after_replay["items"]}
    assert totals_replay == totals_first


def test_expired_plan_cannot_write_cart(client):
    body = _awaiting_tomato_egg(client)
    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        plan = json.loads(task.plan_json)
        plan["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        task.plan_json = json.dumps(plan)
        db.commit()
    finally:
        db.close()

    before_qty = sum(_cart_qty(client, sku) for sku in {i["sku_id"] for i in body["plan"]["items"]})
    confirm = _confirm(client, body["task_id"], body["plan"], body["state_version"])
    assert confirm.status_code == 409
    assert confirm.json()["error"]["code"] == "PLAN_EXPIRED"
    after_qty = sum(_cart_qty(client, sku) for sku in {i["sku_id"] for i in body["plan"]["items"]})
    assert after_qty == before_qty


def test_stale_state_version_cannot_write_cart(client):
    body = _awaiting_tomato_egg(client)
    before = client.get("/api/v1/cart").json()
    confirm = _confirm(
        client,
        body["task_id"],
        body["plan"],
        body["state_version"] - 1,
    )
    assert confirm.status_code == 409
    assert confirm.json()["error"]["code"] == "STALE_STATE"
    after = client.get("/api/v1/cart").json()
    assert after["items"] == before["items"]


def test_non_awaiting_task_cannot_confirm(client):
    body = _awaiting_tomato_egg(client)
    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        task.current_step = "clarifying"
        db.commit()
    finally:
        db.close()

    confirm = _confirm(client, body["task_id"], body["plan"], body["state_version"])
    assert confirm.status_code == 409
    assert confirm.json()["error"]["code"] == "STALE_STATE"


def test_confirm_quantity_exceeds_stock(client):
    body = _awaiting_tomato_egg(client)
    sku = "demo:cake-flour-250g"
    selected = [{"sku_id": sku, "quantity": 31}]

    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        stored_plan = json.loads(task.plan_json)
        stored_plan["mode"] = "alternatives"
        stored_plan["items"] = [
            {
                "sku_id": sku,
                "name": "低筋面粉 250克（小包装）",
                "quantity": 31,
                "unit_price_fen": 680,
                "line_total_fen": 680 * 31,
                "image_path": "demo/baking/cake-flour.svg",
            }
        ]
        stored_plan["total_price_fen"] = 680 * 31
        task.plan_json = json.dumps(stored_plan)
        task.candidate_products_json = json.dumps([sku])
        db.commit()
        plan = stored_plan
    finally:
        db.close()

    confirm = _confirm(
        client,
        body["task_id"],
        plan,
        body["state_version"],
        selected_items=selected,
    )
    assert confirm.status_code == 422
    assert confirm.json()["error"]["code"] == "PRODUCT_UNAVAILABLE"


def test_confirm_rejects_zero_quantity(client):
    body = _awaiting_tomato_egg(client)
    selected = [
        {"sku_id": body["plan"]["items"][0]["sku_id"], "quantity": 0},
        *[
            {"sku_id": item["sku_id"], "quantity": item["quantity"]}
            for item in body["plan"]["items"][1:]
        ],
    ]
    confirm = _confirm(
        client,
        body["task_id"],
        body["plan"],
        body["state_version"],
        selected_items=selected,
    )
    assert confirm.status_code == 422


def test_confirm_respects_existing_cart_qty(client):
    sku = "demo:cake-flour-250g"
    sid = _session(client, page="category", category_id="baking")
    turn = _turn(client, sid, "想做蛋糕，面粉小包装，20元以内")
    assert turn.status_code == 200
    body = turn.json()
    if body["status"] != "awaiting_confirmation" or not body.get("plan"):
        pytest.skip("baking plan not ready")

    add = client.post(
        "/api/v1/cart/items",
        json={"sku_id": sku, "quantity": 29, "expected_cart_version": 0},
    )
    assert add.status_code == 200

    selected = [{"sku_id": sku, "quantity": 2}]
    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        stored_plan = json.loads(task.plan_json)
        stored_plan["mode"] = "alternatives"
        stored_plan["items"] = [
            {
                "sku_id": sku,
                "name": "低筋面粉 250克（小包装）",
                "quantity": 2,
                "unit_price_fen": 680,
                "line_total_fen": 1360,
                "image_path": "demo/baking/cake-flour.svg",
            }
        ]
        stored_plan["total_price_fen"] = 1360
        task.plan_json = json.dumps(stored_plan)
        task.candidate_products_json = json.dumps([sku])
        db.commit()
        plan = stored_plan
    finally:
        db.close()

    confirm = _confirm(
        client,
        body["task_id"],
        plan,
        body["state_version"],
        selected_items=selected,
    )
    assert confirm.status_code == 422
    assert confirm.json()["error"]["code"] == "PRODUCT_UNAVAILABLE"


def test_confirm_rollback_on_failure(client, monkeypatch):
    body = _awaiting_tomato_egg(client)
    from app.services import confirmation_service as cs

    def fail_apply(self, items, *, expected_cart_version=None):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(cs.CartService, "apply_confirm_items", fail_apply)

    before_items = client.get("/api/v1/cart").json()["items"]
    confirm = _confirm(client, body["task_id"], body["plan"], body["state_version"])
    assert confirm.status_code == 500
    assert confirm.json()["error"]["code"] == "INTERNAL_ERROR"
    after_items = client.get("/api/v1/cart").json()["items"]
    assert after_items == before_items

    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        assert task.current_step == "awaiting_confirmation"
        assert task.user_confirmed is False
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

"""O01 confirmation and cart integration tests."""

from __future__ import annotations

import pytest

import uuid

from app.models.cart import Cart, CartItem, CartOperation
from app.models.session import GuideTask
from support import post_turn


def _session(client):
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


def _plan_turn(client, sid):
    turn = post_turn(client, sid, "我想吃番茄炒蛋", None, request_id=str(uuid.uuid4()))
    assert turn.status_code == 200
    return turn.json()


def _confirm(client, task_id, plan, version, key="idem-confirm-1"):
    items = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in plan["items"]
        if i.get("selected", i.get("role", "required") != "pantry")
    ]
    return client.post(
        f"/api/v1/guide/tasks/{task_id}/confirm",
        headers={"Idempotency-Key": key},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": version,
            "selected_items": items,
        },
    )


def test_confirm_writes_cart_and_task(client):
    from app.core.database import SessionLocal

    sid = _session(client)
    body = _plan_turn(client, sid)
    resp = _confirm(client, body["task_id"], body["plan"], body["state_version"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"

    db = SessionLocal()
    try:
        task = db.get(GuideTask, body["task_id"])
        assert task is not None
        assert task.current_step == "completed"
        assert task.user_confirmed is True
        cart = db.query(Cart).first()
        assert cart is not None
        items = db.query(CartItem).filter_by(cart_id=cart.id).all()
        assert len(items) >= 1
        op = db.query(CartOperation).filter_by(idempotency_key="idem-confirm-1").first()
        assert op is not None
        assert op.status == "completed"
    finally:
        db.close()


def test_confirm_idempotent_replay(client):
    sid = _session(client)
    body = _plan_turn(client, sid)
    key = "idem-replay-10"
    first = _confirm(client, body["task_id"], body["plan"], body["state_version"], key)
    assert first.status_code == 200
    for _ in range(9):
        again = _confirm(client, body["task_id"], body["plan"], body["state_version"], key)
        assert again.status_code == 200
        assert again.json()["operation_id"] == first.json()["operation_id"]

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        cart = db.query(Cart).first()
        items = db.query(CartItem).filter_by(cart_id=cart.id).all()
        total_qty = sum(i.quantity for i in items)
        assert total_qty == sum(i["quantity"] for i in first.json()["items_added"])
    finally:
        db.close()


def test_confirm_rejects_stale_task(client):
    sid = _session(client)
    body = _plan_turn(client, sid)
    client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/cancel",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body.get("session_version", 1),
            "expected_state_version": body["state_version"],
        },
    )
    resp = _confirm(client, body["task_id"], body["plan"], body["state_version"], "stale-key")
    assert resp.status_code == 409


def test_confirm_rejects_wrong_state_version(client):
    sid = _session(client)
    body = _plan_turn(client, sid)
    resp = _confirm(
        client,
        body["task_id"],
        body["plan"],
        body["state_version"] - 1,
        "version-key",
    )
    assert resp.status_code == 409


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

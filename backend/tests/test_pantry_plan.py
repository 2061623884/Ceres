"""Pantry optional items and expanded aisle categories."""

from __future__ import annotations

import uuid

import pytest
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


def _confirm(client, task_id, plan, state_version, selected_items):
    return client.post(
        f"/api/v1/guide/tasks/{task_id}/confirm",
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": state_version,
            "selected_items": selected_items,
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


def test_xiaochaorou_plan_includes_pantry_items(client):
    sid = _session(client)
    turn = _turn(client, sid, "我想吃农家小炒肉")
    assert turn.status_code == 200
    body = turn.json()
    assert body["status"] == "awaiting_confirmation"
    plan = body["plan"]
    assert plan is not None
    roles = {item["sku_id"]: item.get("role", "required") for item in plan["items"]}
    required = [sku for sku, role in roles.items() if role == "required"]
    pantry = [sku for sku, role in roles.items() if role == "pantry"]
    assert len(required) >= 2
    assert len(pantry) >= 1
    assert plan["total_price_fen"] == sum(
        item["line_total_fen"]
        for item in plan["items"]
        if item.get("role", "required") == "required"
    )


def test_confirm_without_pantry_skips_seasonings(client):
    sid = _session(client)
    turn = _turn(client, sid, "我想吃农家小炒肉")
    body = turn.json()
    plan = body["plan"]
    required_only = [
        {"sku_id": item["sku_id"], "quantity": item["quantity"]}
        for item in plan["items"]
        if item.get("role", "required") == "required"
    ]
    pantry_skus = {item["sku_id"] for item in plan["items"] if item.get("role") == "pantry"}

    confirm = _confirm(client, body["task_id"], plan, body["state_version"], required_only)
    assert confirm.status_code == 200

    cart_skus = {item["sku_id"] for item in client.get("/api/v1/cart").json()["items"]}
    assert pantry_skus.isdisjoint(cart_skus)


def test_confirm_with_checked_pantry_adds_seasoning(client):
    sid = _session(client)
    turn = _turn(client, sid, "我想吃农家小炒肉")
    body = turn.json()
    plan = body["plan"]
    pantry_item = next(item for item in plan["items"] if item.get("role") == "pantry")
    revision_items = [
        {
            "sku_id": item["sku_id"],
            "quantity": item["quantity"],
            "selected": item.get("role", "required") == "required"
            or item["sku_id"] == pantry_item["sku_id"],
        }
        for item in plan["items"]
    ]
    rev = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body.get("session_version", 1),
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "client_edit_sequence": 1,
            "items": revision_items,
        },
    )
    assert rev.status_code == 200
    revised = rev.json()
    selected = [
        {"sku_id": item["sku_id"], "quantity": item["quantity"]}
        for item in revised["items"]
        if item.get("selected")
    ]

    confirm = _confirm(
        client,
        body["task_id"],
        {**plan, **revised},
        revised["state_version"],
        selected,
    )
    assert confirm.status_code == 200
    cart_skus = {item["sku_id"] for item in client.get("/api/v1/cart").json()["items"]}
    assert pantry_item["sku_id"] in cart_skus


def test_categories_include_new_aisles(client):
    cats = client.get("/api/v1/categories").json()
    ids = {c["id"] for c in cats}
    assert "staple" in ids
    assert "dairy" in ids
    assert "beverage" in ids


def test_demo_staple_skus_resolve(client):
    from app.core.database import SessionLocal
    from app.services.template_plan_service import TemplatePlanService

    db = SessionLocal()
    try:
        svc = TemplatePlanService(db)
        noodle = svc.resolve_sku_for_ingredient("noodle", needed={"quantity_g": 200})
        oil = svc.resolve_sku_for_ingredient("oil", needed={"quantity_ml": 30})
        soy_milk = svc.resolve_sku_for_ingredient("soy_milk", needed={"quantity_ml": 250})
        assert noodle and noodle["sku_id"].startswith("demo:")
        assert oil and oil["sku_id"].startswith("demo:")
        assert soy_milk and soy_milk["sku_id"].startswith("demo:")
    finally:
        db.close()


def test_rice_not_in_condiment_category(client):
    product = client.get("/api/v1/products/demo:rice-2kg").json()
    assert product["category_id"] == "staple"


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

"""U03 revision + confirm integration."""

from __future__ import annotations

import pytest

import uuid
from support import post_turn


def test_revised_plan_confirm_cart_qty(client):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]
    turn = post_turn(client, sid, "我想吃番茄炒蛋", None, request_id=str(uuid.uuid4())).json()
    plan = turn["plan"]
    tomato = next(i for i in plan["items"] if "tomato" in i["sku_id"])
    items = [
        {"sku_id": i["sku_id"], "quantity": 2 if i["sku_id"] == tomato["sku_id"] else i["quantity"], "selected": i.get("selected", i.get("role") != "pantry")}
        for i in plan["items"]
    ]
    rev = client.post(
        f"/api/v1/guide/tasks/{turn['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": turn.get("session_version", 1),
            "expected_state_version": turn["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "client_edit_sequence": 1,
            "items": items,
        },
    ).json()
    selected = [{"sku_id": i["sku_id"], "quantity": i["quantity"]} for i in rev["items"] if i.get("selected")]
    assert rev["outstanding_total_fen"] == rev["selected_total_fen"]
    restored = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["plan"]["outstanding_total_fen"] == rev["outstanding_total_fen"]
    confirm = client.post(
        f"/api/v1/guide/tasks/{turn['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": rev["plan_id"],
            "plan_version": rev["plan_version"],
            "expected_state_version": rev["state_version"],
            "expected_session_version": rev["session_version"],
            "selected_items": selected,
        },
    )
    assert confirm.status_code == 200
    cart = client.get("/api/v1/cart").json()
    tomato_qty = next(i["quantity"] for i in cart["items"] if i["sku_id"] == tomato["sku_id"])
    assert tomato_qty == 2


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

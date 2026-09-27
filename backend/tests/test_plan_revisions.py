"""U03 plan revision tests."""

from __future__ import annotations

import pytest

import uuid
from support import post_turn


def _awaiting_tomato(client):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]
    turn = post_turn(client, sid, "我想吃番茄炒蛋", None, request_id=str(uuid.uuid4())).json()
    return turn


def test_tomato_qty_1_to_2(client):
    body = _awaiting_tomato(client)
    plan = body["plan"]
    tomato = next(i for i in plan["items"] if "tomato" in i["sku_id"])
    items = [
        {"sku_id": i["sku_id"], "quantity": 2 if i["sku_id"] == tomato["sku_id"] else i["quantity"], "selected": True}
        for i in plan["items"]
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
            "items": items,
        },
    )
    assert rev.status_code == 200
    data = rev.json()
    revised_tomato = next(i for i in data["items"] if "tomato" in i["sku_id"])
    assert revised_tomato["quantity"] == 2
    assert data["selected_total_fen"] == tomato["unit_price_fen"] * 2 + sum(
        i["line_total_fen"] for i in data["items"] if "tomato" not in i["sku_id"] and i.get("selected")
    )
    messages = client.get(f"/api/v1/guide/sessions/{body['session_id']}/messages").json()["messages"]
    assert not any(str(m.get("content", "")).startswith("方案已更新") for m in messages)


def test_tomato_plan_uses_demo_photo(client):
    body = _awaiting_tomato(client)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    assert str(tomato.get("image_path") or "").endswith(".jpg")
    assert tomato.get("image_kind") == "photo"


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

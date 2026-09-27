"""N01 task continuity: modifications keep active template."""

from __future__ import annotations

import pytest

import uuid
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


def _turn(client, sid, message, task_id=None, version=0, request_id=None):
    previous = {"task_id": task_id, "state_version": version}
    return post_turn(
        client, sid, message, previous, request_id=request_id or str(uuid.uuid4())
    )


def test_tomato_egg_people_change_keeps_ingredients(client):
    sid = _session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋").json()
    assert first["status"] == "awaiting_confirmation"
    task_id = first["task_id"]
    first_skus = {i["sku_id"] for i in first["plan"]["items"]}

    second = _turn(
        client,
        sid,
        "改成4个人",
        task_id=task_id,
        version=first["state_version"],
    )
    assert second.status_code == 200
    body = second.json()
    assert body["task_id"] == task_id
    assert body["status"] == "awaiting_confirmation"
    names = " ".join(i.get("name") or "" for i in body["plan"]["items"])
    assert "番茄" in names or "Tomato" in names
    assert "鸡蛋" in names or "Egg" in names
    assert "泡打粉" not in names
    second_skus = {i["sku_id"] for i in body["plan"]["items"]}
    assert first_skus == second_skus or second_skus.issubset(
        {s for s in first_skus if "egg" in s or "tomato" in s}
    )


def test_tomato_egg_low_budget_degrades_not_random(client):
    sid = _session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋").json()
    second = _turn(
        client,
        sid,
        "预算10元以内",
        task_id=first["task_id"],
        version=first["state_version"],
    )
    assert second.status_code == 200
    body = second.json()
    if body.get("plan"):
        names = " ".join(i.get("name") or "" for i in body["plan"]["items"])
        assert "泡打粉" not in names
    else:
        assert body["status"] in ("degraded", "clarifying", "awaiting_confirmation")


def test_same_modification_text_uses_new_request_ids(client):
    sid = _session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋").json()
    req_a = str(uuid.uuid4())
    req_b = str(uuid.uuid4())
    r1 = _turn(
        client,
        sid,
        "改成4个人",
        task_id=first["task_id"],
        version=first["state_version"],
        request_id=req_a,
    )
    assert r1.status_code == 200
    v = r1.json()["state_version"]
    r2 = _turn(
        client,
        sid,
        "改成4个人",
        task_id=first["task_id"],
        version=v,
        request_id=req_b,
    )
    assert r2.status_code == 200


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

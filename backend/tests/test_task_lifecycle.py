"""U02 task lifecycle tests."""

from __future__ import annotations

import pytest

import uuid
from support import post_turn


def _session(client):
    return client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]


def _turn(client, sid, message, task_id=None, version=0, session_version=None):
    previous = {"task_id": task_id, "state_version": version}
    if session_version is not None:
        previous["session_version"] = session_version
    return post_turn(client, sid, message, previous, request_id=str(uuid.uuid4()))


def test_cancel_then_new_goal_not_stale(client):
    sid = _session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋").json()
    cancel = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/cancel",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": first.get("session_version", 1),
            "expected_state_version": first["state_version"],
        },
    )
    assert cancel.status_code == 200
    second = _turn(client, sid, "我想吃宫保鸡丁", task_id=first["task_id"], version=cancel.json()["state_version"])
    assert second.status_code == 200
    assert second.json()["task_id"] != first["task_id"]


def test_switch_goal_gongbao(client):
    sid = _session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋").json()
    second = _turn(client, sid, "取消这个，改做宫保鸡丁", task_id=first["task_id"], version=first["state_version"])
    assert second.status_code == 200
    body = second.json()
    assert body["task_id"] != first["task_id"]
    names = " ".join(i.get("name") or "" for i in (body.get("plan") or {}).get("items", []))
    assert "花生" in names or "peanut" in names.lower() or "鸡胸" in names


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

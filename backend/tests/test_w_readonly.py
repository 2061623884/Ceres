"""W01 W02 workflow readonly turns via /turns."""

from __future__ import annotations

import pytest

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


def _turn(client, sid, message, previous=None):
    previous = previous or {}
    resp = post_turn(client, sid, message, previous)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plan(client, message="我想吃番茄炒蛋"):
    sid = _session(client)
    first = _turn(client, sid, message)
    assert first.get("plan"), first
    return sid, first


def test_w01_readonly_explain_keeps_plan_without_new_task(client):
    sid, first = _plan(client)
    task_id = first["task_id"]
    state_version = first["state_version"]
    session_version = first["session_version"]
    plan_id = first["plan"]["plan_id"]

    following = _turn(
        client,
        sid,
        "为什么选这些",
        {
            "task_id": task_id,
            "state_version": state_version,
            "session_version": session_version,
        },
    )
    assert following["plan_effect"] == "keep"
    assert following["task_id"] == task_id
    assert following["state_version"] == state_version
    assert following.get("plan") is None

    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session["task_id"] == task_id
    assert session.get("plan", {}).get("plan_id") == plan_id


def test_w02_greeting_without_task_does_not_create_task(client):
    sid = _session(client)
    before = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert before.get("task_id") in (None, "")

    turn = _turn(client, sid, "你好")
    assert turn["plan_effect"] == "keep"
    assert turn.get("task_id") in (None, "")
    assert turn.get("plan") is None

    after = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert after.get("task_id") in (None, "")


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

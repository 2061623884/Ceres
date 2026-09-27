"""U01 conversation history tests."""

from __future__ import annotations

import pytest

import uuid
from support import post_turn


def _session(client):
    return client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]


def test_messages_persist_and_paginate(client):
    sid = _session(client)
    turn = post_turn(client, sid, "我想吃番茄炒蛋", None, request_id=str(uuid.uuid4()))
    assert turn.status_code == 200
    page = client.get(f"/api/v1/guide/sessions/{sid}/messages")
    assert page.status_code == 200
    body = page.json()
    assert len(body["messages"]) >= 2
    assert body["messages"][0]["sequence"] < body["messages"][-1]["sequence"]


def test_include_messages_on_session(client):
    sid = _session(client)
    post_turn(client, sid, "你好", None, request_id=str(uuid.uuid4()))
    sess = client.get(f"/api/v1/guide/sessions/{sid}?include_messages=1")
    assert sess.status_code == 200
    assert sess.json().get("messages")


def test_turn_idempotent_replay(client):
    sid = _session(client)
    rid = str(uuid.uuid4())
    payload = {
        "request_id": rid,
        "message": "我想吃番茄炒蛋",
        "expected_task_id": None,
        "expected_state_version": 0,
    }
    first = post_turn(
        client, sid, payload["message"], None, request_id=payload["request_id"]
    )
    second = post_turn(
        client, sid, payload["message"], None, request_id=payload["request_id"]
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

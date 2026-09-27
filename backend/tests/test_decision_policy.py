"""``plan_effect`` is what the retired routing table used to decide.

``DecisionPolicy`` mapped an interpreted turn onto a route *and* an effect
(``keep`` / ``replace`` / ``clear``). The route is gone — the model proposes and
the server compiles — but the effect is still an external contract the client
reads on every turn. It is asserted here directly, from the API, instead of from
a table of routes that no longer exists.
"""

from __future__ import annotations

import uuid

import pytest

from support import create_session, post_turn
from support.semantic_agent import request_new, reply_only

TOMATO = "番茄炒蛋"


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


def _plan(client, sid: str, semantic_provider) -> dict:
    semantic_provider([{
        "understanding": request_new("dish", TOMATO, people=2),
        "lookups": [{"kind": "dish", "query": TOMATO}],
    }])
    body = turn(client, sid, "我想吃番茄炒蛋，两个人").json()
    assert body.get("plan"), body
    return body


def test_a_mutation_turn_replaces_the_plan(client, semantic_provider):
    sid = create_session(client)
    body = _plan(client, sid, semantic_provider)
    assert body["plan_effect"] == "replace"
    assert body["status"] == "awaiting_confirmation"


def test_a_chat_turn_on_a_live_plan_keeps_it(client, semantic_provider):
    sid = create_session(client)
    plan = _plan(client, sid, semantic_provider)

    semantic_provider([reply_only("这道菜主要是鸡蛋和番茄。")])
    body = turn(
        client,
        sid,
        "这道菜怎么做",
        {"task_id": plan["task_id"], "state_version": plan["state_version"]},
    ).json()
    assert body["plan_effect"] == "keep"
    assert body["plan"] is None


def test_a_turn_with_nothing_understandable_keeps_the_plan(client, semantic_provider):
    """An empty proposal is a reported failure, and never clears a live plan."""
    sid = create_session(client)
    plan = _plan(client, sid, semantic_provider)

    semantic_provider([{}])
    body = turn(
        client,
        sid,
        "……",
        {"task_id": plan["task_id"], "state_version": plan["state_version"]},
    ).json()
    assert body["plan_effect"] == "keep"
    assert body["action_results"], body
    assert any(
        r.get("type") == "understanding_failed" for r in body["action_results"]
    ), body


@pytest.mark.parametrize("message", ["取消", "算了"])
def test_a_cancel_word_does_not_cancel_behind_the_model(
    client, semantic_provider, message
):
    """The server compiles; it does not re-read the sentence for a cancel verb.

    A model that proposes nothing leaves the plan exactly as it is. Cancelling is
    an explicit action (``/cancel``), not a word the server pattern-matches.
    """
    sid = create_session(client)
    plan = _plan(client, sid, semantic_provider)

    semantic_provider([reply_only("好的。")])
    body = turn(
        client,
        sid,
        message,
        {"task_id": plan["task_id"], "state_version": plan["state_version"]},
    ).json()
    assert body["plan_effect"] == "keep"
    assert body["status"] != "cancelled"

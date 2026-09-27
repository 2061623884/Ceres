"""Behavior of the single Proposal → Decision → Graph route boundary."""

from __future__ import annotations

import pytest

from support import create_session, post_turn


def _turn(client, session_id, message, previous=None):
    response = post_turn(client, session_id, message, previous)
    assert response.status_code == 200, response.text
    return response.json()


def test_chat_with_mutation_preserves_reply_and_never_writes(client, semantic_provider):
    provider = semantic_provider([{
        "reply": "好的，聊聊火锅。",
        "understanding": {"speech_act": "chat"},
        "mutations": [{"verb": "add", "candidate_ref": "unknown", "name": "火锅"}],
    }])
    sid = create_session(client)
    body = _turn(client, sid, "火锅是什么？")

    assert body["route"] == "chat"
    assert body["message"] == "好的，聊聊火锅。"
    assert body["plan_effect"] == "keep" and body["plan"] is None
    assert not any(row.get("code") == "WRITE_BLOCKED" for row in body["action_results"])
    assert not any(row.get("type") in ("mutation", "mutation_refused", "read_only") for row in body["action_results"])
    assert len(provider.requests) == 1


def test_retrieve_second_call_only_supplies_reply(client, semantic_provider, monkeypatch):
    from app.agent.graph.nodes import understand

    gate = understand.evaluate_gate
    decisions = []

    def counted(*args, **kwargs):
        decision = gate(*args, **kwargs)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(understand, "evaluate_gate", counted)
    provider = semantic_provider([
        {"understanding": {"speech_act": "ask_fact"}, "queries": [{"kind": "recommend"}]},
        {"reply": "检索结果里有番茄炒蛋。", "mutations": [{"verb": "invented"}]},
    ])
    sid = create_session(client)
    body = _turn(client, sid, "有什么推荐？")

    assert [decision.route for decision in decisions] == ["retrieve"]
    assert provider.requests[1]["read_only"] is True
    assert provider.requests[1]["query_results"]
    assert body["message"] == "检索结果里有番茄炒蛋。"
    assert body["plan_effect"] == "keep" and body["plan"] is None
    assert not any(row.get("code") == "WRITE_BLOCKED" for row in body["action_results"])


def test_named_purchase_with_lookup_uses_mutation_route(client, semantic_provider, monkeypatch):
    from app.agent.graph.nodes import understand

    gate = understand.evaluate_gate
    routes = []

    def counted(*args, **kwargs):
        decision = gate(*args, **kwargs)
        routes.append((decision.route, decision.mutation_action))
        return decision

    monkeypatch.setattr(understand, "evaluate_gate", counted)
    provider = semantic_provider([{
        "understanding": {
            "speech_act": "request_action",
            "goal_relation": "new",
            "new_goal": {"kind": "meal_plan", "target_name": "番茄炒蛋"},
        },
        "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
    }])
    sid = create_session(client)
    body = _turn(client, sid, "我想吃番茄炒蛋")

    assert routes == [("mutation", "prepare")]
    assert body["plan_effect"] == "replace", body
    assert body["plan"] and body["plan"]["items"]
    assert len(provider.requests) == 1


def test_chat_after_a_plan_does_not_consume_its_mutation(client, semantic_provider):
    provider = semantic_provider([
        {
            "understanding": {
                "speech_act": "request_action", "goal_relation": "new",
                "new_goal": {"kind": "meal_plan", "target_name": "番茄炒蛋"},
            },
            "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
        },
        {
            "reply": "好的，清单还在。",
            "understanding": {"speech_act": "chat"},
            "mutations": [{"verb": "add", "candidate_ref": "unknown", "name": "火锅"}],
        },
    ])
    sid = create_session(client)
    first = _turn(client, sid, "我想吃番茄炒蛋")
    before = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert first["plan_effect"] == "replace"

    second = _turn(client, sid, "好的", first)
    after = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert second["route"] == "chat"
    assert second["message"] == "好的，清单还在。"
    assert second["plan_effect"] == "keep"
    assert after == before
    assert not any(row.get("code") == "WRITE_BLOCKED" for row in second["action_results"])
    assert len(provider.requests) == 2


def test_mutation_with_an_unissued_ref_cannot_write(client, semantic_provider):
    semantic_provider([{
        "understanding": {
            "speech_act": "request_action", "goal_relation": "new",
            "new_goal": {"kind": "meal_plan", "target_name": "番茄炒蛋"},
        },
        "mutations": [{"verb": "add", "candidate_ref": "unknown", "name": "番茄炒蛋"}],
    }])
    sid = create_session(client)
    body = _turn(client, sid, "我想吃番茄炒蛋")
    assert body["plan_effect"] == "keep" and body["plan"] is None
    assert not any(row.get("saved") for row in body["action_results"])
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] is None


@pytest.mark.parametrize("route,proposal", [
    ("answer", {"reply": "锅热后再下油。", "understanding": {"speech_act": "ask_fact"}}),
    ("clarify", {"reply": "想吃什么菜？", "understanding": {
        "speech_act": "request_action", "goal_relation": "new",
        "new_goal": {"kind": "meal_decision"},
    }}),
    ("refuse", {"reply": "这件事做不了。", "understanding": {
        "speech_act": "request_action", "goal_relation": "new",
        "new_goal": {"kind": "unsupported"},
    }}),
])
def test_non_mutation_decisions_finish_through_answer_respond(
    client, semantic_provider, monkeypatch, route, proposal
):
    from app.agent.graph.nodes import understand

    gate = understand.evaluate_gate
    seen = []

    def counted(*args, **kwargs):
        decision = gate(*args, **kwargs)
        seen.append(decision.route)
        return decision

    monkeypatch.setattr(understand, "evaluate_gate", counted)
    semantic_provider([proposal])
    sid = create_session(client)
    body = _turn(client, sid, "说说看")
    assert seen == [route]
    assert body["plan_effect"] == "keep" and body["plan"] is None
    assert body["assistant_message_id"]

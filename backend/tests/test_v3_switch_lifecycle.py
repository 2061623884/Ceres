"""V3 opening and role-switch lifecycle through the public chat API."""

from types import SimpleNamespace

import pytest

from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, kev, new_order, opening, send
from test_semantic_phase1_purchase import indexed_client
from support import create_session, post_turn
from support.semantic_agent import lookup_then_add_id, request_new


def test_momo_shopping_request_returns_to_keke_only_after_user_consent(
    indexed_client, kev, semantic_provider
):
    message = "想买一盒新鲜鸡蛋"
    provider = semantic_provider([{
        **request_new("product", "新鲜鸡蛋 6枚装", quantity=1),
        "lookups": [{"kind": "product", "query": "新鲜鸡蛋 6枚装"}],
    }])
    choices, calls = kev
    choices.append("suggest_switch")
    chat = opening(indexed_client, role="momo")
    assert chat["role"] == "momo"

    routed = events(send(indexed_client, chat, message, "r08-momo-to-keke"))
    route = routed[0]["payload"]
    assert route["decision"] == "suggest_switch"
    assert route["current_role"] == "momo" and route["target_role"] == "keke"
    assert route["prompt_mode"] == "automatic"
    assert routed[-1]["payload"]["business_not_run"] is True
    assert calls[0]["state"]["utterance"] == message
    assert provider.requests == []

    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    displayed = indexed_client.post(f"{path}/prompt-displayed", json={"handoff_id": route["handoff_id"]})
    assert displayed.status_code == 200
    switched = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": route["handoff_id"], "accept": True,
    })
    assert switched.status_code == 200
    completed = next(event["payload"] for event in events(switched)
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["route"] == "prepare"
    assert completed["plan"] is not None, completed
    assert completed["plan"]["items"][0]["sku_id"] == "demo:eggs-fresh-6pack"
    assert provider.requests[0]["user_message"] == message
    assert indexed_client.get(path).json()["role"] == "keke"


def test_momo_handoff_keeps_relevant_dialogue_and_resumes_existing_guide_state(
    indexed_client, kev, semantic_provider, monkeypatch
):
    provider = semantic_provider([
        *lookup_then_add_id("product", "可乐 330毫升", "demo:cola-330ml"),
        *lookup_then_add_id("product", "新鲜鸡蛋 6枚装", "demo:eggs-fresh-6pack", relation="append"),
    ])
    guide_session_id = create_session(indexed_client)
    existing = post_turn(indexed_client, guide_session_id, "买一瓶可乐 330毫升", request_id="target-plan")
    assert existing.status_code == 200, existing.json()
    existing_state = existing.json()
    assert existing_state["plan"]["items"][0]["sku_id"] == "demo:cola-330ml"
    assert existing_state["state_version"] > 0 and existing_state["session_version"] > 0

    mercury_session_id = indexed_client.post("/api/v1/mercury/sessions").json()["session_id"]
    opened = indexed_client.post("/api/v1/chat/openings", json={
        "guide_session_id": guide_session_id,
        "mercury_session_id": mercury_session_id,
        "role": "momo",
    })
    assert opened.status_code == 200, opened.text
    chat = opened.json()
    previous_user = "刚才问的是鲜鸡蛋 6枚装的退货期限。"
    previous_answer = "你问的是鲜鸡蛋 6枚装的退货期限；具体条件要以门店政策为准。"

    def answer(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=previous_answer, tool_calls=[]))])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=answer))))
    choices, route_calls = kev
    choices.append("stay_current")
    first_momo = events(send(indexed_client, chat, previous_user, "momo-context-source"))
    assert first_momo[-1]["type"] == "turn.completed"
    choices.append("suggest_switch")
    message = "我想买一盒新鲜鸡蛋 6枚装"
    routed = events(send(indexed_client, chat, message, "momo-context-handoff"))
    route = routed[0]["payload"]
    assert route["decision"] == "suggest_switch" and route["target_role"] == "keke"
    routed_dialogue = route_calls[-1]["state"]["recent_dialogue"]
    assert {("user", previous_user), ("assistant", previous_answer)} <= {
        (row["role"], row["content"]) for row in routed_dialogue
    }

    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    assert indexed_client.post(f"{path}/prompt-displayed", json={"handoff_id": route["handoff_id"]}).status_code == 200
    switched = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": route["handoff_id"], "accept": True,
    })
    assert switched.status_code == 200
    completed = next(event["payload"] for event in events(switched)
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["plan"] is not None, completed
    assert {item["sku_id"] for item in completed["plan"]["items"]} >= {
        "demo:cola-330ml", "demo:eggs-fresh-6pack",
    }
    request = provider.requests[-1]
    assert request["user_message"] == message
    assert any(row == {"role": "assistant", "content": previous_answer}
               for row in request["recent_messages"])
    assert any(row == {"role": "user", "content": previous_user}
               for row in request["recent_messages"])
    assert any(item["sku_id"] == "demo:cola-330ml"
               for item in request["current_plan"]["items"])


def test_manual_selection_resumes_pending_handoff_but_later_selection_only_restores(
    client, kev, monkeypatch
):
    chat = opening(client)
    order = new_order(client)
    tool_calls = []

    def answer(**kwargs):
        tool_calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="我已查看这张模拟订单。", tool_calls=[]))])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=answer))))
    kev[0].append("suggest_switch")
    route = events(send(client, chat, "这张订单到哪了", "manual-pending", order_id=order["order_id"]))[0]["payload"]

    path = f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream"
    resumed_pending = client.post(path, json={"target_role": "momo", "accept": True})
    assert resumed_pending.status_code == 200
    assert events(resumed_pending)[-1]["type"] == "turn.completed"
    assert len(tool_calls) == 1

    back_to_keke = client.post(path, json={"target_role": "keke", "accept": True})
    assert events(back_to_keke)[0]["payload"]["status"] == "resumed"
    restored_momo = client.post(path, json={"target_role": "momo", "accept": True})
    restored_events = events(restored_momo)
    assert restored_events[0]["payload"]["status"] == "resumed"
    assert all(event["type"] != "turn.completed" for event in restored_events)
    assert len(tool_calls) == 1


@pytest.mark.parametrize("accept", [True, False], ids=["accept", "reject"])
def test_answered_switch_question_is_not_pending_for_next_route(
    client, kev, semantic_provider, monkeypatch, accept
):
    chat = opening(client)
    order = new_order(client)
    if not accept:
        semantic_provider([{"reply": "好，我继续协助你选购。"}])

    def answer(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="我已查看这张模拟订单。", tool_calls=[]))])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=answer))))
    choices, calls = kev
    choices.append("suggest_switch")
    first = events(send(client, chat, "这张订单到哪了", "answered-switch-question",
                        order_id=order["order_id"]))
    route = first[0]["payload"]
    assert route["target_role"] == "momo"
    assert "是否切换" in first[-1]["payload"]["message"]

    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    assert client.post(f"{path}/prompt-displayed", json={"handoff_id": route["handoff_id"]}).status_code == 200
    switched = client.post(f"{path}/switches/stream", json={
        "target_role": "momo", "handoff_id": route["handoff_id"], "accept": accept,
    })
    assert switched.status_code == 200
    switch_events = events(switched)
    if accept:
        assert switch_events[-1]["type"] == "turn.completed"
    else:
        assert switch_events[0]["payload"]["status"] == "rejected"

    choices.append("stay_current")
    next_message = "继续查看这张订单" if accept else "继续帮我选可乐"
    next_turn = events(send(client, chat, next_message, "after-answering-switch-question",
                            **({"order_id": order["order_id"]} if accept else {})))
    assert next_turn[0]["payload"]["decision"] == "stay_current"
    assert calls[-1]["state"]["pending_question"] is None
    assert calls[-1]["state"]["current_role"] == (
        "Momo after-sales" if accept else "Keke shopping"
    )
    assert next_turn[-1]["type"] == "turn.completed"


def test_display_quota_survives_get_rejection_and_role_switch_until_explicit_close(
    indexed_client, kev, semantic_provider
):
    semantic_provider([{"reply": "我可以继续帮你选购。"}])
    chat = opening(indexed_client)
    order = new_order(indexed_client)
    path = f"/api/v1/chat/openings/{chat['opening_id']}"

    kev[0].append("suggest_switch")
    first_route = events(send(indexed_client, chat, "这张订单到哪了", "quota-first",
                              order_id=order["order_id"]))[0]["payload"]
    assert first_route["prompt_mode"] == "automatic"
    marked = indexed_client.post(f"{path}/prompt-displayed", json={"handoff_id": first_route["handoff_id"]})
    assert marked.status_code == 200 and marked.json()["prompt_displayed"] is True
    assert indexed_client.get(path).json()["prompt_displayed"] is True
    rejected = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "momo", "handoff_id": first_route["handoff_id"], "accept": False,
    })
    assert events(rejected)[0]["payload"]["status"] == "rejected"

    kev[0].append("stay_current")
    continued = events(send(indexed_client, chat, "继续帮我看看可乐", "quota-new-message"))
    assert continued[-1]["type"] == "turn.completed"
    for target_role in ("momo", "keke"):
        manual = indexed_client.post(f"{path}/switches/stream", json={
            "target_role": target_role, "accept": True,
        })
        assert events(manual)[0]["payload"]["status"] == "resumed"
        assert indexed_client.get(path).json()["prompt_displayed"] is True

    kev[0].append("suggest_switch")
    second_route = events(send(indexed_client, chat, "这张订单的配送如何", "quota-second",
                               order_id=order["order_id"]))[0]["payload"]
    assert second_route["prompt_mode"] == "fixed_entry"
    assert indexed_client.get(path).json()["prompt_displayed"] is True

    closed = indexed_client.delete(path)
    assert closed.status_code == 204
    assert indexed_client.get(path).status_code == 404
    reopened = indexed_client.post("/api/v1/chat/openings", json={
        "guide_session_id": chat["guide_session_id"],
        "mercury_session_id": chat["mercury_session_id"],
    })
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["opening_id"] != chat["opening_id"]
    assert reopened.json()["guide_session_id"] == chat["guide_session_id"]
    assert reopened.json()["mercury_session_id"] == chat["mercury_session_id"]
    assert reopened.json()["prompt_displayed"] is False


def test_unclear_object_clarification_does_not_assume_cancellation(client, kev):
    kev[0].append("clarify")
    chat = opening(client)
    result = events(send(client, chat, "那个怎么办", "clarify-object"))
    assert result[0]["payload"]["decision"] == "clarify"
    completion = result[-1]["payload"]
    assert completion["business_not_run"] is True
    message = completion["message"]
    assert "取消" not in message
    assert "采购清单项" in message and "已下单订单" in message

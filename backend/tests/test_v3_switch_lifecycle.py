"""V3 opening and role-switch lifecycle through the public chat API."""

import json
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


@pytest.mark.parametrize("accept_continuation", [True, False], ids=["continue", "cancel"])
def test_failed_aftersales_offers_explicit_resume_with_original_request_and_tool_result(
    indexed_client, kev, semantic_provider, monkeypatch, accept_continuation
):
    order = new_order(indexed_client)
    original_request = f"先为这笔订单申请退货，然后继续帮我买一瓶可乐。"
    provider = semantic_provider(lookup_then_add_id(
        "product", "可乐 330毫升", "demo:cola-330ml", quantity=1,
    ))
    chat = opening(indexed_client)
    choices, route_calls = kev
    choices.append("suggest_switch")
    routed = events(send(indexed_client, chat, original_request, "compound-aftersales-shopping",
                         order_id=order["order_id"]))
    route = routed[0]["payload"]
    assert route["target_role"] == "momo"

    tool_results = []
    tool_calls = []

    def model(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] == "user":
            assert messages[-1]["content"] == original_request
            msg = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                id="return-request", function=SimpleNamespace(
                    name="create_return", arguments=json.dumps({
                        "order_id": order["order_id"],
                        "item_id": order["items"][0]["item_id"],
                    }),
                ),
            )])
        else:
            result = json.loads(messages[-1]["content"])
            tool_results.append(result)
            tool_calls.append("create_return")
            msg = SimpleNamespace(content="订单尚未签收，退货申请失败；我已暂停。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    accepted = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "momo", "handoff_id": route["handoff_id"], "accept": True,
    })
    aftersales_events = events(accepted)
    assert tool_results[0]["ok"] is False and tool_results[0]["error"] == "NOT_DELIVERED"
    assert "签收" in tool_results[0]["message"]
    aftersales_completions = [event["payload"] for event in aftersales_events
                              if event["type"] == "turn.completed"
                              and not event["payload"].get("business_not_run")]
    assert "退货申请失败" in aftersales_completions[-1]["final_text"]
    assert provider.requests == []

    continuation_routes = [event["payload"] for event in aftersales_events
                           if event["type"] == "service.route"
                           and event["payload"].get("target_role") == "keke"]
    assert len(continuation_routes) == 1, "completed aftersales turn must offer an explicit Keke continuation"
    continuation_prompt = next(
        event["payload"]["message"] for event in aftersales_events
        if event["type"] == "turn.completed" and event["payload"].get("business_not_run")
    )
    user_facing_next_step = (
        tool_results[0]["message"] in continuation_prompt
        and "继续选购" in continuation_prompt
        and "售后工具" not in continuation_prompt
        and "一并带入" not in continuation_prompt
        and "已处理步骤" not in continuation_prompt
    )
    assert user_facing_next_step, "continuation should state the result and offer a plain next step"
    continuation_route = continuation_routes[0]
    assert continuation_route["decision"] == "suggest_switch"
    assert continuation_route.get("decision_source") == "aftersales_tool_result", "continuation comes from the server workflow"
    assert continuation_route.get("raw_choice") is None, "a workflow continuation has no Kev choice"
    displayed = indexed_client.post(f"{path}/prompt-displayed", json={
        "handoff_id": continuation_route["handoff_id"],
    })
    assert displayed.status_code == 200, "the automatic continuation's visible choice must be acknowledged"
    assert displayed.json()["handoff_id"] == continuation_route["handoff_id"]
    assert displayed.json()["prompt_displayed"] is True

    resumed = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": continuation_route["handoff_id"],
        "accept": accept_continuation,
    })
    resumed_events = events(resumed)
    if not accept_continuation:
        assert resumed_events[0]["payload"]["status"] == "rejected"
        assert provider.requests == []
        assert tool_calls == ["create_return"]
        assert route_calls[0]["state"]["utterance"] == original_request
        return

    completed = next(event["payload"] for event in resumed_events
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["plan"]["items"][0]["sku_id"] == "demo:cola-330ml"
    request = provider.requests[0]
    assert request["user_message"] == original_request
    assert any(original_request in row["content"] for row in request["recent_messages"])
    assert any("NOT_DELIVERED" in row["content"] for row in request["recent_messages"])

    replayed = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": continuation_route["handoff_id"], "accept": True,
    })
    replayed_events = events(replayed)
    assert any(event["type"] == "turn.completed" and "plan" in event["payload"]
               for event in replayed_events)
    assert len(provider.requests) == 1
    assert tool_calls == ["create_return"]
    assert route_calls[0]["state"]["utterance"] == original_request


@pytest.mark.parametrize("accept_continuation", [True, False], ids=["continue", "cancel"])
def test_pending_refund_survives_final_momo_error_and_continuation_requires_choice(
    indexed_client, kev, semantic_provider, monkeypatch, accept_continuation
):
    provider = semantic_provider([
        *lookup_then_add_id("product", "新鲜鸡蛋 6枚装", "demo:eggs-fresh-6pack", quantity=1),
        *lookup_then_add_id("product", "可乐 330毫升", "demo:cola-330ml", quantity=1),
    ])
    guide_session_id = create_session(indexed_client)
    purchased = post_turn(
        indexed_client, guide_session_id, "买一盒新鲜鸡蛋 6枚装", request_id="aftersales-source-purchase",
    ).json()
    source_plan = purchased["plan"]
    assert source_plan["items"][0]["sku_id"] == "demo:eggs-fresh-6pack"
    source_confirm = indexed_client.post(
        f"/api/v1/guide/tasks/{purchased['task_id']}/confirm",
        headers={"Idempotency-Key": "aftersales-source-confirm"},
        json={
            "plan_id": source_plan["plan_id"],
            "plan_version": source_plan["plan_version"],
            "expected_state_version": purchased["state_version"],
            "expected_session_version": purchased["session_version"],
            "selected_items": [{
                "sku_id": row["sku_id"], "quantity": row["quantity"],
            } for row in source_plan["items"] if row.get("selected", True)],
        },
    )
    assert source_confirm.status_code == 200
    source_cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in source_cart["items"]] == [
        ("demo:eggs-fresh-6pack", 1),
    ]
    checkout = indexed_client.post(
        "/api/v1/cart/checkout", json={"expected_cart_version": source_cart["version"]},
    )
    assert checkout.status_code == 200
    order = checkout.json()["order"]
    assert order["status"] == "paid"
    assert order["items"][0]["product_name"] == "鲜鸡蛋 6枚装"
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

    mercury_session_id = indexed_client.post("/api/v1/mercury/sessions").json()["session_id"]
    chat = indexed_client.post("/api/v1/chat/openings", json={
        "guide_session_id": guide_session_id,
        "mercury_session_id": mercury_session_id,
        "role": "momo",
    }).json()
    selected = indexed_client.post(
        f"/api/v1/mercury/sessions/{mercury_session_id}/order",
        json={"order_id": order["order_id"]},
    )
    assert selected.status_code == 200

    original_request = "先为这笔订单申请退款，然后继续帮我买一瓶可乐。"
    choices, route_calls = kev
    choices.append("stay_current")
    tool_calls = []
    tool_results = []

    def model(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] == "user":
            assert messages[-1]["content"] == original_request
            tool_calls.append("create_refund")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="", tool_calls=[SimpleNamespace(id="refund-request", function=SimpleNamespace(
                    name="create_refund", arguments=json.dumps({
                        "order_id": order["order_id"], "reason": "用户明确申请退款",
                    }),
                ))]), )])
        tool_results.append(json.loads(messages[-1]["content"]))
        raise RuntimeError("controlled final answer failure after refund write")

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    before_resume_requests = len(provider.requests)
    aftersales_events = events(send(
        indexed_client, chat, original_request, "refund-then-continue", order_id=order["order_id"],
    ))
    assert aftersales_events[0]["payload"]["decision"] == "stay_current"
    assert any(event["type"] == "error" and event["payload"]["code"] == "MERCURY_MODEL_FAILED"
               for event in aftersales_events)
    assert tool_results[0]["ok"] is True
    assert tool_results[0]["data"]["order_id"] == order["order_id"]
    assert tool_results[0]["data"]["status"] == "pending"
    assert len(provider.requests) == before_resume_requests

    continuation_route = next(
        event["payload"] for event in aftersales_events
        if event["type"] == "service.route" and event["payload"].get("target_role") == "keke"
    )
    continuation_prompt = next(
        event["payload"]["message"] for event in aftersales_events
        if event["type"] == "turn.completed" and event["payload"].get("business_not_run")
    )
    actual_result_message = tool_results[0]["data"]["message"]
    assert actual_result_message in continuation_prompt
    assert "继续选购" in continuation_prompt
    assert continuation_route["handoff_id"]
    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    assert indexed_client.post(f"{path}/prompt-displayed", json={
        "handoff_id": continuation_route["handoff_id"],
    }).status_code == 200

    switched = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": continuation_route["handoff_id"],
        "accept": accept_continuation,
    })
    switch_events = events(switched)
    if not accept_continuation:
        assert switch_events[0]["payload"]["status"] == "rejected"
        assert len(provider.requests) == before_resume_requests
        assert indexed_client.get("/api/v1/cart").json()["items"] == []
        assert tool_calls == ["create_refund"]
        return

    continued = next(event["payload"] for event in switch_events
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert continued["plan"]["items"][0]["sku_id"] == "demo:cola-330ml"
    assert continued["status"] == "awaiting_confirmation"
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    request = provider.requests[-1]
    assert request["user_message"] == original_request
    continuation_row = next(
        row["content"] for row in request["recent_messages"]
        if row["content"].startswith("Momo after-sales continuation: ")
    )
    record = json.loads(continuation_row.removeprefix("Momo after-sales continuation: "))
    assert record["original_request"] == original_request
    assert record["selected_object"]["order_id"] == order["order_id"]
    assert record["tool_results"][0]["result"]["data"]["status"] == "pending"

    replayed = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": continuation_route["handoff_id"], "accept": True,
    })
    assert any(event["type"] == "turn.completed" and "plan" in event["payload"]
               for event in events(replayed))
    assert len(provider.requests) == before_resume_requests + 1
    assert tool_calls == ["create_refund"]

    confirm = indexed_client.post(
        f"/api/v1/guide/tasks/{continued['task_id']}/confirm",
        headers={"Idempotency-Key": "aftersales-continuation-confirm"},
        json={
            "plan_id": continued["plan"]["plan_id"],
            "plan_version": continued["plan"]["plan_version"],
            "expected_state_version": continued["state_version"],
            "expected_session_version": continued["session_version"],
            "selected_items": [{
                "sku_id": row["sku_id"], "quantity": row["quantity"],
            } for row in continued["plan"]["items"] if row.get("selected", True)],
        },
    )
    assert confirm.status_code == 200
    final_cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in final_cart["items"]] == [
        ("demo:cola-330ml", 1),
    ]
    assert provider.remaining() == 0


def test_direct_momo_order_chat_offers_resume_after_actual_aftersales_tool(
    indexed_client, kev, semantic_provider, monkeypatch
):
    order = new_order(indexed_client)
    original_request = "先申请这笔订单退货，再继续帮我买一瓶可乐。"
    provider = semantic_provider(lookup_then_add_id(
        "product", "可乐 330毫升", "demo:cola-330ml", quantity=1,
    ))
    chat = opening(indexed_client, role="momo")
    choices, route_calls = kev
    choices.append("stay_current")
    tool_results = []
    tool_calls = []

    def model(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] == "user":
            assert messages[-1]["content"] == original_request
            msg = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                id="return-request", function=SimpleNamespace(
                    name="create_return", arguments=json.dumps({
                        "order_id": order["order_id"],
                        "item_id": order["items"][0]["item_id"],
                    }),
                ),
            )])
        else:
            result = json.loads(messages[-1]["content"])
            tool_results.append(result)
            tool_calls.append("create_return")
            msg = SimpleNamespace(content="订单尚未签收，退货申请失败；我已暂停。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    aftersales_events = events(send(indexed_client, chat, original_request, "direct-momo-resume",
                                    order_id=order["order_id"]))
    assert aftersales_events[0]["payload"]["decision"] == "stay_current"
    assert tool_results[0]["ok"] is False and tool_results[0]["error"] == "NOT_DELIVERED"
    assert provider.requests == []

    continuation_routes = [event["payload"] for event in aftersales_events
                           if event["type"] == "service.route"
                           and event["payload"].get("target_role") == "keke"]
    assert len(continuation_routes) == 1, "direct Momo order chat must offer an explicit Keke continuation"
    continuation_route = continuation_routes[0]
    path = f"/api/v1/chat/openings/{chat['opening_id']}"
    resumed = indexed_client.post(f"{path}/switches/stream", json={
        "target_role": "keke", "handoff_id": continuation_route["handoff_id"], "accept": True,
    })
    resumed_events = events(resumed)
    completed = next(event["payload"] for event in resumed_events
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["plan"]["items"][0]["sku_id"] == "demo:cola-330ml"
    assert provider.requests[0]["user_message"] == original_request
    assert any("NOT_DELIVERED" in row["content"] for row in provider.requests[0]["recent_messages"])
    assert route_calls[0]["state"]["current_role"] == "Momo after-sales"
    assert route_calls[0]["state"]["selected_object"]["order_id"] == order["order_id"]
    assert tool_calls == ["create_return"]


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

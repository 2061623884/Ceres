"""Ceres Next 03: observable capability routing through the public guide turn."""

import json

from support import create_session, post_turn, send_turn
from support.semantic_agent import Continuation, reply_only, request_new

from test_semantic_phase1_purchase import indexed_client  # noqa: F401
from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, opening, send


def test_chat_capability_keeps_chat_out_of_purchase(
    internal_trace_headers, client, semantic_provider, kev_api
):
    semantic_provider([reply_only("你好，我可以帮你选购商品。")])
    session_id = create_session(client)

    response = post_turn(client, session_id, "你好")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == "你好，我可以帮你选购商品。"
    assert body["plan"] is None

    trace = client.get(
        f"/api/v1/internal/traces/{body['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    events = trace.json()["events"]
    capability_call = next(
        (
            event
            for event in events
            if event["phase"] == "model_call_completed"
            and json.loads(event["output_summary"]).get("stage") == "capability"
        ),
        None,
    )
    assert capability_call is not None, events
    detail = json.loads(capability_call["output_summary"])
    assert detail["capability"] == "chat"
    assert detail["criteria_version"] == "ceres-guide-capabilities-v1"
    assert set(detail["criteria"]) == {
        "category_exploration",
        "purchase_modify",
        "facts_qa",
        "chat",
    }
    assert detail["raw_response"]["answers"]["capability"]["choice"] == "chat"
    assert capability_call["duration_ms"] >= 0
    assert len([call for call in kev_api["calls"] if "capability" in call["request"]["questions"]]) == 1


def test_verified_product_type_answer_skips_semantic_understanding(
    internal_trace_headers, indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "category_exploration"

    def show_snack_types(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "薯片和饼干都有，可以先选类型。",
            "display_refs": [row["ref"] for row in matches],
        }

    def show_selected_type(request):
        results = request.get("query_results") or []
        matches = results[0].get("matches", []) if results else []
        chips = next(
            (row for row in matches if row["product_type"] == "potato_chips"),
            None,
        )
        response = {
            "target": {"kind": "category", "name": "薯片", "intent": "explore"},
            "lookups": [{"kind": "product", "query": "薯片"}],
            "reply": "有原味薯片可选。",
            "display_refs": [chips["ref"]] if chips else [],
        }
        answer = request.get("clarification_answer")
        if answer:
            response["resolved_questions"] = [answer["question_id"]]
        return response

    provider = semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            show_snack_types,
            show_selected_type,
            show_selected_type,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()
    broad = send_turn(indexed_client, session_id, "来点零食")
    trace = indexed_client.get(
        f"/api/v1/internal/traces/{broad['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    broad_calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert [call["stage"] for call in broad_calls] == [
        "capability", "understanding", "answer"
    ]
    assert broad_calls[0]["capability"] == "category_exploration"
    assert broad_calls[0]["branch"] == "semantic_understanding"

    question = broad["pending_clarifications"][0]
    chips = next(option for option in question["options"] if option["label"] == "薯片")
    kev_api["choices"]["capability"] = "purchase_modify"

    selected = send_turn(
        indexed_client,
        session_id,
        "薯片",
        broad,
        clarification_answer={
            "question_id": question["question_id"],
            "option_id": chips["id"],
        },
    )

    assert selected["pending_clarifications"] == []
    assert selected["plan"] is None
    assert "原味薯片70克袋装" in selected["message"]
    assert "苏打饼干100克盒装" not in selected["message"]
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    trace = indexed_client.get(
        f"/api/v1/internal/traces/{selected['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert [call["stage"] for call in calls] == ["capability", "answer"], calls
    assert calls[0]["capability"] == "purchase_modify"
    assert calls[0]["branch"] == "direct_product_type_workflow"


def test_public_v3_category_exploration_returns_current_type_options(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "category_exploration"

    def show_available_types(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "薯片和饼干都有，可以先选类型。",
            "display_refs": [row["ref"] for row in matches],
        }

    provider = semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            Continuation(show_available_types),
        ]
    )
    before_cart = indexed_client.get("/api/v1/cart").json()
    chat = opening(indexed_client)

    result = events(send(indexed_client, chat, "来点零食", "cap-category"))

    assert result[0]["payload"]["decision"] == "stay_current"
    completed = result[-1]["payload"]
    question = completed["pending_clarifications"][0]
    assert question["slot"] == "product_type"
    assert {option["label"] for option in question["options"]} == {"薯片", "饼干"}
    assert completed["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == before_cart
    assert provider.requests[0]["capability"] == "category_exploration"


def test_public_v3_purchase_modify_prepares_a_plan_without_cart_write(
    internal_trace_headers, indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"
    product = "可口可乐零度无糖汽水500ml瓶装"
    provider = semantic_provider(
        [
            {
                **request_new(
                    "product", product, quantity=2, constraints={"budget_yuan": 20}
                ),
                "lookups": [{"kind": "product", "query": product}],
            }
        ]
    )
    before_cart = indexed_client.get("/api/v1/cart").json()
    chat = opening(indexed_client)

    result = events(
        send(
            indexed_client,
            chat,
            f"买两瓶{product}，预算20元",
            "cap-purchase",
        )
    )

    assert result[0]["payload"]["decision"] == "stay_current"
    completed = result[-1]["payload"]
    assert completed["plan"] is not None and completed["plan"]["can_confirm"]
    assert completed["plan"]["items"][0]["quantity"] == 2
    assert completed["plan"]["items"][0]["sku_id"] == "demo:cn-coke-zero-500ml-bottle"
    assert provider.requests[0]["capability"] == "purchase_modify"
    assert indexed_client.get("/api/v1/cart").json() == before_cart

    trace = indexed_client.get(
        f"/api/v1/internal/traces/{completed['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert [call["stage"] for call in calls] == ["capability", "understanding"]


def test_public_v3_facts_qa_answers_from_policy_source(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "facts_qa"

    def answer_from_policy(request):
        policies = request["query_results"][0]["policies"]
        fact = next(row for row in policies if row["policy_id"] == "P-DEL-01")
        return {
            "reply": f"模拟门店：{fact['content']} 来源 {fact['policy_id']} {fact['title']}。"
        }

    provider = semantic_provider(
        [
            {"reads": [{"kind": "policy", "topic": "一般配送时间"}]},
            Continuation(answer_from_policy),
        ]
    )
    before_cart = indexed_client.get("/api/v1/cart").json()
    before_orders = indexed_client.get("/api/v1/orders").json()
    chat = opening(indexed_client)

    result = events(send(indexed_client, chat, "一般配送时间", "cap-facts"))

    assert result[0]["payload"]["decision"] == "stay_current"
    completed = result[-1]["payload"]
    assert "P-DEL-01" in completed["message"]
    assert any(
        row["policy_id"] == "P-DEL-01"
        for row in provider.requests[1]["query_results"][0]["policies"]
    )
    assert completed["task_id"] is None and completed["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == before_cart
    assert indexed_client.get("/api/v1/orders").json() == before_orders
    assert provider.requests[0]["capability"] == "facts_qa"


def test_public_v3_chat_does_not_create_a_purchase_task(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "chat"
    semantic_provider([reply_only("你好，我可以帮你选购商品。")])
    before_cart = indexed_client.get("/api/v1/cart").json()
    before_orders = indexed_client.get("/api/v1/orders").json()
    chat = opening(indexed_client)

    result = events(send(indexed_client, chat, "你好", "cap-chat"))

    assert result[0]["payload"]["decision"] == "stay_current"
    completed = result[-1]["payload"]
    assert completed["message"] == "你好，我可以帮你选购商品。"
    assert completed["task_id"] is None and completed["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == before_cart
    assert indexed_client.get("/api/v1/orders").json() == before_orders
    assert kev_api["calls"][0]["request"]["questions"].keys() == {"service"}
    assert kev_api["calls"][1]["request"]["questions"].keys() == {"capability"}


def test_public_v3_multi_target_append_keeps_main_understanding_and_prior_requirements(
    internal_trace_headers, indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"
    cola = "可口可乐零度无糖汽水500ml瓶装"
    eggs = "鲜鸡蛋 6枚装"
    first_message = f"买两瓶{cola}，预算20元"
    append_message = f"再加一盒{eggs}，原来两瓶可乐和20元预算都保留。"
    provider = semantic_provider(
        [
            {
                **request_new("product", cola, quantity=2, constraints={"budget_yuan": 20}),
                "lookups": [{"kind": "product", "query": cola}],
            },
            {
                **request_new(
                    "product", eggs, relation="append", quantity=1,
                    constraints={"budget_yuan": 20},
                ),
                "lookups": [{"kind": "product", "query": eggs}],
            },
        ]
    )
    before_cart = indexed_client.get("/api/v1/cart").json()
    chat = opening(indexed_client)

    first_events = events(send(indexed_client, chat, first_message, "cap-multi-first"))
    first = first_events[-1]["payload"]
    assert first["plan"] is not None
    current = indexed_client.get(
        f"/api/v1/guide/sessions/{chat['guide_session_id']}"
    ).json()
    appended_events = events(
        send(
            indexed_client,
            chat,
            append_message,
            "cap-multi-append",
            expected_task_id=current["task_id"],
            expected_state_version=current["state_version"],
        )
    )
    completed = appended_events[-1]["payload"]

    assert provider.requests[1]["user_message"] == append_message
    assert provider.requests[1]["capability"] == "purchase_modify"
    assert provider.requests[1]["requirements"]["budget_fen"] == 2000
    targets = {target["name"] for target in completed["plan"]["targets"]}
    assert targets == {cola, eggs}
    quantities = {item["sku_id"]: item["quantity"] for item in completed["plan"]["items"]}
    assert quantities == {
        "demo:cn-coke-zero-500ml-bottle": 2,
        "demo:eggs-fresh-6pack": 1,
    }
    assert indexed_client.get("/api/v1/cart").json() == before_cart

    trace = indexed_client.get(
        f"/api/v1/internal/traces/{completed['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert [call["stage"] for call in calls] == ["capability", "understanding"]
    assert calls[0]["branch"] == "semantic_understanding"

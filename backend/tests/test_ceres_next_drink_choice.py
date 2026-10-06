"""Public chat behavior for drinks and candidate filtering."""

import json
import uuid

from support import create_session, send_turn
from support.semantic_agent import Continuation, pick

from test_semantic_phase1_purchase import indexed_client  # noqa: F401


def test_broad_drink_purchase_asks_for_a_supplied_type_before_preparing_a_plan(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"
    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "饮料",
                    "intent": "buy",
                    "quantity": 2,
                },
                "constraints": {"budget_yuan": 20},
                "lookups": [{"kind": "product", "query": "饮料"}],
            }
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    response = send_turn(indexed_client, session_id, "买点饮料，两瓶，预算20元")

    questions = response["pending_clarifications"]
    assert len(questions) == 1, response
    question = questions[0]
    assert question["slot"] == "product_type"
    assert question["question_id"]
    labels = {option["label"] for option in question["options"]}
    assert {"可乐", "茶", "饮用水", "桃汁饮料"} <= labels
    assert all(option["id"] for option in question["options"])
    assert response["plan"] is None
    assert not response.get("product_cards")
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_unaffordable_drink_types_are_not_offered(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"
    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "饮料",
                    "intent": "buy",
                    "quantity": 2,
                },
                "constraints": {"budget_yuan": 3},
                "lookups": [{"kind": "product", "query": "饮料"}],
            }
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    response = send_turn(indexed_client, session_id, "买点饮料，两瓶，预算3元")

    assert response["pending_clarifications"] == [], response
    assert "没有符合条件的饮品" in response["message"]
    assert response["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_cola_type_choice_displays_products_with_actual_filter_options(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"

    def show_cola_products(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "有多款可乐可选，也可以按品牌或规格筛选。",
            "display_refs": [
                row["ref"] for row in matches if row.get("family_id") == "cola"
            ],
        }

    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "饮料",
                    "intent": "buy",
                },
                "constraints": {"budget_yuan": 20},
                "lookups": [{"kind": "product", "query": "饮料"}],
            },
            Continuation(show_cola_products),
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    broad = send_turn(indexed_client, session_id, "买点饮料，预算20元")
    type_question = broad["pending_clarifications"][0]
    cola = next(
        option for option in type_question["options"] if option["label"] == "可乐"
    )
    selected = send_turn(
        indexed_client,
        session_id,
        "可乐",
        broad,
        clarification_answer={
            "question_id": type_question["question_id"],
            "option_id": cola["id"],
        },
    )

    filter_questions = [
        question
        for question in selected["pending_clarifications"]
        if question["slot"] == "product_filter"
    ]
    assert len(filter_questions) == 1
    assert len(selected["product_cards"]) >= 2
    assert {card["brand"] for card in selected["product_cards"]} == {
        "可口可乐",
        "百事可乐",
    }
    labels = {option["label"] for option in filter_questions[0]["options"]}
    assert {"品牌：可口可乐", "品牌：百事可乐"} <= labels
    assert any(label.startswith("单件容量：") for label in labels)
    assert selected["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_brand_filter_answer_reads_only_matching_products_without_understanding(
    indexed_client,
    internal_trace_headers,
    semantic_provider,
    kev_api,
):
    kev_api["choices"]["capability"] = "purchase_modify"

    def show_cola_products(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "有多款可乐可选，也可以按品牌或规格筛选。",
            "display_refs": [
                row["ref"] for row in matches if row.get("family_id") == "cola"
            ],
        }

    def apply_pepsi_filter(request):
        if not request.get("query_results"):
            answer = request["clarification_answer"]
            return {
                "target": {"kind": "category", "name": "可乐", "intent": "explore"},
                "constraints": {"specification": {"brand": "百事可乐"}},
                "lookups": [{"kind": "product", "query": "可乐"}],
                "resolved_questions": [answer["question_id"]],
            }
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "筛选结果如下。",
            "display_refs": [
                row["ref"] for row in matches if row.get("brand") == "百事可乐"
            ],
        }

    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "饮料",
                    "intent": "buy",
                },
                "constraints": {"budget_yuan": 20},
                "lookups": [{"kind": "product", "query": "饮料"}],
            },
            Continuation(show_cola_products),
            apply_pepsi_filter,
            Continuation(apply_pepsi_filter),
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    broad = send_turn(indexed_client, session_id, "买点饮料，预算20元")
    type_question = broad["pending_clarifications"][0]
    cola = next(option for option in type_question["options"] if option["label"] == "可乐")
    selected_type = send_turn(
        indexed_client,
        session_id,
        "可乐",
        broad,
        clarification_answer={
            "question_id": type_question["question_id"],
            "option_id": cola["id"],
        },
    )
    filter_question = next(
        question
        for question in selected_type["pending_clarifications"]
        if question["slot"] == "product_filter"
    )
    pepsi = next(
        option
        for option in filter_question["options"]
        if option["label"] == "品牌：百事可乐"
    )
    assert pepsi["id"] == (
        'product_filter:{"query":"可乐","field":"brand","value":"百事可乐"}'
    )

    filtered = send_turn(
        indexed_client,
        session_id,
        pepsi["label"],
        selected_type,
        clarification_answer={
            "question_id": filter_question["question_id"],
            "option_id": pepsi["id"],
        },
    )

    assert filtered["pending_clarifications"] == []
    assert {card["brand"] for card in filtered["product_cards"]} == {"百事可乐"}
    assert filtered["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == cart_before
    trace = indexed_client.get(
        f"/api/v1/internal/traces/{filtered['trace_id']}",
        headers=internal_trace_headers,
    )
    calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert [call["stage"] for call in calls] == ["capability", "answer"]
    assert calls[0]["branch"] == "direct_product_filter_workflow"


def test_drink_type_and_filter_keep_budget_quantity_until_explicit_confirmation(
    indexed_client, semantic_provider, kev_api
):
    kev_api["choices"]["capability"] = "purchase_modify"

    def show_cola_products(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "有多款可乐可选，也可以按品牌或规格筛选。",
            "display_refs": [
                row["ref"] for row in matches if row.get("family_id") == "cola"
            ],
        }

    def answer_bottle_specification(request):
        question = next(
            question
            for question in request["pending_clarifications"]
            if question["slot"] == "product_filter"
        )
        return {
            "target": {"kind": "category", "name": "可乐", "intent": "explore"},
            "constraints": {"specification": {"packaging": "bottle"}},
            "lookups": [{"kind": "product", "query": "可乐"}],
            "resolved_questions": [question["question_id"]],
        }

    def show_bottled_products(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "这些瓶装可乐符合筛选条件。",
            "display_refs": [row["ref"] for row in matches],
        }

    def prepare_plan(request):
        pepsi = next(
            row
            for row in request["displayed_candidates"]
            if row["target_id"] == "demo:cn-coke-original-500ml-bottle"
        )
        requirements = request["requirements"]
        return {
            **pick(
                "product",
                pepsi,
                quantity=requirements.get("quantity"),
                constraints={
                    "budget_yuan": requirements["budget_fen"] / 100,
                },
            ),
        }

    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "饮料",
                    "intent": "buy",
                    "quantity": 2,
                },
                "constraints": {"budget_yuan": 20},
                "lookups": [{"kind": "product", "query": "饮料"}],
            },
            Continuation(show_cola_products),
            answer_bottle_specification,
            Continuation(show_bottled_products),
            prepare_plan,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    broad = send_turn(indexed_client, session_id, "买点饮料，两瓶，预算20元")
    type_question = broad["pending_clarifications"][0]
    cola = next(option for option in type_question["options"] if option["label"] == "可乐")
    selected_type = send_turn(
        indexed_client,
        session_id,
        cola["label"],
        broad,
        clarification_answer={
            "question_id": type_question["question_id"],
            "option_id": cola["id"],
        },
    )
    filter_question = next(
        question
        for question in selected_type["pending_clarifications"]
        if question["slot"] == "product_filter"
    )
    assert filter_question["options"]
    selected_filter = send_turn(indexed_client, session_id, "换成瓶装的", selected_type)
    assert selected_filter["pending_clarifications"] == []
    assert selected_filter["plan"] is None
    assert selected_filter["product_cards"]
    assert all("瓶装" in card["name"] for card in selected_filter["product_cards"])
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    planned = send_turn(indexed_client, session_id, "生成清单", selected_filter)
    plan = planned["plan"]
    assert plan is not None and plan["can_confirm"]
    assert len(plan["items"]) == 1
    item = plan["items"][0]
    assert item["sku_id"] == "demo:cn-coke-original-500ml-bottle"
    assert item["quantity"] == 2
    assert item["unit_price_fen"] * item["quantity"] <= 2000
    assert indexed_client.get(f"/api/v1/guide/sessions/{session_id}").json()[
        "constraints_summary"
    ]["budget_fen"] == 2000
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    confirmed = indexed_client.post(
        f"/api/v1/guide/tasks/{planned['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": planned["state_version"],
            "expected_session_version": planned["session_version"],
            "selected_items": [{"sku_id": item["sku_id"], "quantity": 2}],
        },
    )
    assert confirmed.status_code == 200
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in cart["items"]] == [
        ("demo:cn-coke-original-500ml-bottle", 2)
    ]

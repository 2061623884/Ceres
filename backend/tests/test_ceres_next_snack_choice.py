"""Public chat behavior for the next-stage snack choice flow."""

import uuid

from support import create_session, post_turn, send_turn
from support.semantic_agent import pick

from test_semantic_phase1_purchase import indexed_client  # noqa: F401


def test_broad_snack_request_asks_for_available_type_before_showing_products(
    indexed_client, semantic_provider
):
    semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            lambda request: {
                "reply": "薯片和饼干都有，可以先选类型。",
                "display_refs": [
                    row["ref"]
                    for row in request["query_results"][0]["matches"]
                ],
            },
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    response = send_turn(indexed_client, session_id, "来点零食")

    questions = response["pending_clarifications"]
    assert len(questions) == 1, response
    question = questions[0]
    assert question["question_id"]
    assert "零食" in question["question"]
    options = question["options"]
    assert {option["label"] for option in options} == {"薯片", "饼干"}
    assert all(option["id"] for option in options)
    assert len({option["id"] for option in options}) == 2
    assert response["plan"] is None
    assert not response.get("product_cards")
    assert all(
        name not in response["message"]
        for name in ("原味薯片70克袋装", "苏打饼干100克盒装")
    )
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_broad_snack_purchase_asks_for_type_before_preparing_a_plan(
    indexed_client, semantic_provider
):
    def select_chips(_request):
        return {
            "target": {"kind": "category", "name": "薯片", "intent": "explore"},
            "lookups": [{"kind": "product", "query": "薯片"}],
        }

    def show_chips(request):
        chips = next(
            row
            for row in request["query_results"][0]["matches"]
            if row["product_type"] == "potato_chips"
        )
        return {"reply": "有原味薯片可选。", "display_refs": [chips["ref"]]}

    def prepare_plan(request):
        chips = next(
            row
            for row in request["displayed_candidates"]
            if row["target_id"] == "demo:snack-original-potato-chips-70g-bag"
        )
        requirements = request.get("requirements") or {}
        budget_fen = requirements.get("budget_fen")
        constraints = (
            {"budget_yuan": budget_fen / 100} if budget_fen is not None else None
        )
        return pick(
            "product",
            chips,
            quantity=requirements.get("quantity"),
            constraints=constraints,
        )

    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "零食",
                    "intent": "buy",
                    "quantity": 2,
                },
                "constraints": {"budget_yuan": 15},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            select_chips,
            show_chips,
            prepare_plan,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    response = send_turn(indexed_client, session_id, "来点零食，两包，预算15元")

    questions = response["pending_clarifications"]
    assert len(questions) == 1, response
    question = questions[0]
    assert question["question_id"]
    assert question["slot"] == "product_type"
    assert {option["label"] for option in question["options"]} == {"薯片", "饼干"}
    assert {option["id"] for option in question["options"]} == {
        "product_type:potato_chips",
        "product_type:soda_crackers",
    }
    assert response["plan"] is None
    assert not response.get("product_cards")
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    question = questions[0]
    chips_option = next(
        option for option in question["options"] if option["label"] == "薯片"
    )
    selected = send_turn(
        indexed_client,
        session_id,
        "薯片",
        response,
        clarification_answer={
            "question_id": question["question_id"],
            "option_id": chips_option["id"],
        },
    )
    assert selected["pending_clarifications"] == []
    assert selected["plan"] is None
    assert "原味薯片70克袋装" in selected["message"]
    assert "苏打饼干100克盒装" not in selected["message"]
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    planned = send_turn(indexed_client, session_id, "生成清单", selected)
    plan = planned["plan"]
    assert plan is not None and plan["can_confirm"]
    assert len(plan["items"]) == 1
    item = plan["items"][0]
    assert item["sku_id"] == "demo:snack-original-potato-chips-70g-bag"
    assert item["quantity"] == 2
    assert item["unit_price_fen"] * item["quantity"] <= 1500
    assert indexed_client.get("/api/v1/guide/sessions/" + session_id).json()[
        "constraints_summary"
    ]["budget_fen"] == 1500
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
    assert confirmed.status_code == 200, confirmed.text
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in cart["items"]] == [
        ("demo:snack-original-potato-chips-70g-bag", 2)
    ]


def test_choosing_snack_type_by_identity_clears_question_and_shows_matching_products(
    indexed_client, semantic_provider
):
    def choose_type(_request):
        return {
            "target": {"kind": "category", "name": "薯片", "intent": "explore"},
            "lookups": [{"kind": "product", "query": "薯片"}],
        }

    def show_selected_type(request):
        matches = request["query_results"][0]["matches"]
        assert matches
        assert all(row["product_type"] == "potato_chips" for row in matches)
        return {"reply": "有原味薯片可选。", "display_refs": [matches[0]["ref"]]}

    semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            lambda request: {
                "reply": "薯片和饼干都有，可以先选类型。",
                "display_refs": [row["ref"] for row in request["query_results"][0]["matches"]],
            },
            choose_type,
            show_selected_type,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()
    before = send_turn(indexed_client, session_id, "来点零食")
    question = before["pending_clarifications"][0]
    chips = next(option for option in question["options"] if option["label"] == "薯片")

    after = send_turn(
        indexed_client,
        session_id,
        "薯片",
        before,
        clarification_answer={"question_id": question["question_id"], "option_id": chips["id"]},
    )

    assert after["pending_clarifications"] == []
    assert after["plan"] is None
    assert "原味薯片70克袋装" in after["message"]
    assert "苏打饼干100克盒装" not in after["message"]
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_snack_type_answer_rejects_an_option_without_the_current_question_identity(
    indexed_client, semantic_provider
):
    semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            lambda request: {
                "reply": "薯片和饼干都有，可以先选类型。",
                "display_refs": [
                    row["ref"] for row in request["query_results"][0]["matches"]
                ],
            },
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()
    before = send_turn(indexed_client, session_id, "来点零食")
    question = before["pending_clarifications"][0]
    chips = next(option for option in question["options"] if option["label"] == "薯片")

    rejected = post_turn(
        indexed_client,
        session_id,
        "薯片",
        before,
        clarification_answer={
            "question_id": question["question_id"],
            "option_id": "product_type:another-question",
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "STALE_CLARIFICATION"
    current = indexed_client.get(f"/api/v1/guide/sessions/{session_id}").json()
    assert current["pending_clarifications"] == [question]
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_snack_type_can_be_answered_with_free_text_and_does_not_leave_stale_question(
    indexed_client, semantic_provider
):
    def show_snack_types(request):
        return {
            "reply": "薯片和饼干都有，可以先选类型。",
            "display_refs": [
                row["ref"] for row in request["query_results"][0]["matches"]
            ],
        }

    def answer_with_crackers(request):
        question = next(
            item
            for item in request["pending_clarifications"]
            if item["slot"] == "product_type"
        )
        return {
            "target": {"kind": "category", "name": "饼干", "intent": "explore"},
            "lookups": [{"kind": "product", "query": "苏打饼干"}],
            "resolved_questions": [question["question_id"]],
        }

    def show_crackers(request):
        crackers = next(
            row
            for row in request["query_results"][0]["matches"]
            if row["product_type"] == "soda_crackers"
        )
        return {"reply": "有苏打饼干可选。", "display_refs": [crackers["ref"]]}

    semantic_provider(
        [
            {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            show_snack_types,
            answer_with_crackers,
            show_crackers,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()
    before = send_turn(indexed_client, session_id, "来点零食")

    after = send_turn(indexed_client, session_id, "我想要苏打饼干", before)

    assert after["pending_clarifications"] == []
    assert after["plan"] is None
    assert "苏打饼干100克盒装" in after["message"]
    assert "原味薯片70克袋装" not in after["message"]
    assert indexed_client.get("/api/v1/cart").json() == cart_before


def test_snack_choice_carries_budget_and_quantity_through_plan_to_explicit_confirmation(
    indexed_client, semantic_provider
):
    def show_snack_types(request):
        matches = request["query_results"][0]["matches"]
        return {
            "reply": "薯片和饼干都有，可以先选类型。",
            "display_refs": [row["ref"] for row in matches],
        }

    def show_chips(request):
        chips = next(
            row
            for row in request["query_results"][0]["matches"]
            if row["product_type"] == "potato_chips"
        )
        return {"reply": "有原味薯片可选。", "display_refs": [chips["ref"]]}

    def prepare_plan(request):
        chips = next(
            row
            for row in request["displayed_candidates"]
            if row["target_id"] == "demo:snack-original-potato-chips-70g-bag"
        )
        requirements = request.get("requirements") or {}
        budget_fen = requirements.get("budget_fen")
        constraints = (
            {"budget_yuan": budget_fen / 100} if budget_fen is not None else None
        )
        return pick(
            "product",
            chips,
            quantity=requirements.get("quantity"),
            constraints=constraints,
        )

    semantic_provider(
        [
            {
                "target": {
                    "kind": "category",
                    "name": "零食",
                    "intent": "explore",
                    "quantity": 2,
                },
                "constraints": {"budget_yuan": 15},
                "lookups": [{"kind": "product", "query": "零食"}],
            },
            show_snack_types,
            {
                "target": {"kind": "category", "name": "薯片", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "薯片"}],
            },
            show_chips,
            prepare_plan,
        ]
    )
    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()

    broad = send_turn(indexed_client, session_id, "来点零食，两包，预算15元")
    question = broad["pending_clarifications"][0]
    chips_option = next(
        option for option in question["options"] if option["label"] == "薯片"
    )
    selected = send_turn(
        indexed_client,
        session_id,
        "薯片",
        broad,
        clarification_answer={
            "question_id": question["question_id"],
            "option_id": chips_option["id"],
        },
    )
    assert selected["pending_clarifications"] == []
    assert selected["plan"] is None
    assert "原味薯片70克袋装" in selected["message"]
    assert "苏打饼干100克盒装" not in selected["message"]
    assert indexed_client.get("/api/v1/cart").json() == cart_before

    planned = send_turn(indexed_client, session_id, "生成清单", selected)
    plan = planned["plan"]
    assert plan is not None and plan["can_confirm"]
    assert len(plan["items"]) == 1
    item = plan["items"][0]
    assert item["sku_id"] == "demo:snack-original-potato-chips-70g-bag"
    assert item["quantity"] == 2
    assert item["unit_price_fen"] * item["quantity"] <= 1500
    assert indexed_client.get("/api/v1/guide/sessions/" + session_id).json()[
        "constraints_summary"
    ]["budget_fen"] == 1500
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
    assert confirmed.status_code == 200, confirmed.text
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in cart["items"]] == [
        ("demo:snack-original-potato-chips-70g-bag", 2)
    ]

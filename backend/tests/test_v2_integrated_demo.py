"""Two deterministic fixture-only integrated purchase and order journeys.

The business path remains real; only the semantic proposal and Mercury's
external OpenAI boundary are controlled. Retrieval is the existing lexical
test index and is not evidence of vector or live-model acceptance.
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core import database as db_module
from app.core.config import get_settings
from support import create_session, send_turn
from support.semantic_agent import Continuation, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_two_run_v2_purchase_history_checkout_and_mercury_journey(
    indexed_client, semantic_provider, monkeypatch, run
):
    preference = "我平时做番茄炒蛋喜欢清淡少盐"
    source = {}

    def prepare_four_person_dish(request):
        assert any(
            row["source"] == "explicit" and row["content"] == preference
            for row in request["memories"]
        )
        return request_new("dish", "番茄炒蛋", people=4, mode="self_cook")

    def answer_from_history(request):
        history = next(row for row in request["query_results"] if row["kind"] == "history")
        row = history["plans"][0]
        assert row["plan_id"] == source["plan_id"]
        assert row["plan_version"] == source["plan_version"]
        return {
            "reply": f"历史方案 {row['plan_id']} 仅供参考；本次要重新配货并确认。",
            "display_refs": [row["targets"][0]["ref"]],
        }

    semantic_provider(
        [
            {"memory": {"verb": "save", "category": "user", "content": preference}},
            prepare_four_person_dish,
            {"reads": [{"kind": "history", "topic": "番茄炒蛋"}]},
            Continuation(answer_from_history),
            prepare_four_person_dish,
        ]
    )

    first_session = create_session(indexed_client)
    owner = indexed_client.cookies.get("sg_owner_id")
    saved = send_turn(indexed_client, first_session, f"请记住：{preference}")
    saved_memory = next(row for row in saved["action_results"] if row["type"] == "memory")["records"][0]
    assert (saved_memory["category"], saved_memory["source"], saved_memory["expires_at"]) == (
        "user", "explicit", None
    )

    first = send_turn(indexed_client, first_session, "今晚四个人自己做番茄炒蛋")
    first_plan = first["plan"]
    assert first_plan["targets"][0]["name"] == "番茄炒蛋"
    assert first_plan["targets"][0]["people"] == 4
    required = [row for row in first_plan["items"] if row["role"] == "required"]
    pantry = [row for row in first_plan["items"] if row["role"] == "pantry"]
    assert required and all(row["selected"] for row in required)
    assert all(not row["selected"] for row in pantry)
    assert first_plan["selected_total_fen"] == sum(
        row["unit_price_fen"] * row["quantity"] for row in first_plan["items"] if row["selected"]
    )
    assert all(
        row["line_total_fen"] == (row["unit_price_fen"] * row["quantity"] if row["selected"] else 0)
        for row in first_plan["items"]
    )
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

    egg = next(row for row in first_plan["items"] if row["sku_id"] == "demo:eggs-fresh-6pack")
    tomato = next(row for row in first_plan["items"] if row["sku_id"] == "demo:tomato-fresh-500g")
    first_revision_response = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": first["session_version"],
            "expected_state_version": first["state_version"],
            "base_plan_id": first_plan["plan_id"],
            "base_plan_version": first_plan["plan_version"],
            "coverage_intent": "partial_ok",
            "items": [
                {"sku_id": row["sku_id"], "quantity": row["quantity"], "selected": row["sku_id"] == egg["sku_id"]}
                for row in first_plan["items"]
            ],
        },
    )
    assert first_revision_response.status_code == 200, first_revision_response.json()
    first_revision = first_revision_response.json()
    assert first_revision["selected_total_fen"] == egg["unit_price_fen"] * egg["quantity"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    source.update(plan_id=first_revision["plan_id"], plan_version=first_revision["plan_version"])

    first_confirmation = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": first_revision["plan_id"],
            "plan_version": first_revision["plan_version"],
            "expected_session_version": first_revision["session_version"],
            "expected_state_version": first_revision["state_version"],
            "selected_items": [{"sku_id": egg["sku_id"], "quantity": egg["quantity"]}],
        },
    )
    assert first_confirmation.status_code == 200, first_confirmation.json()
    first_cart = indexed_client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"]) for row in first_cart["items"]] == [
        (egg["sku_id"], egg["quantity"])
    ]

    second_session = create_session(indexed_client)
    found = send_turn(indexed_client, second_session, "查询我之前的番茄炒蛋方案")
    assert source["plan_id"] in found["message"]
    assert found["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == first_cart

    rebuilt = send_turn(
        indexed_client,
        second_session,
        "参考上次方案，这次仍按四人重新配番茄炒蛋清单",
        found,
    )
    second_plan = rebuilt["plan"]
    assert rebuilt["task_id"] != first["task_id"]
    assert second_plan["plan_id"] != source["plan_id"]
    assert second_plan["targets"][0]["people"] == 4
    assert indexed_client.get("/api/v1/cart").json() == first_cart

    second_tomato = next(row for row in second_plan["items"] if row["sku_id"] == tomato["sku_id"])
    second_revision_response = indexed_client.post(
        f"/api/v1/guide/tasks/{rebuilt['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": rebuilt["session_version"],
            "expected_state_version": rebuilt["state_version"],
            "base_plan_id": second_plan["plan_id"],
            "base_plan_version": second_plan["plan_version"],
            "coverage_intent": "partial_ok",
            "items": [
                {"sku_id": row["sku_id"], "quantity": row["quantity"], "selected": row["sku_id"] == tomato["sku_id"]}
                for row in second_plan["items"]
            ],
        },
    )
    assert second_revision_response.status_code == 200, second_revision_response.json()
    second_revision = second_revision_response.json()
    assert second_revision["selected_total_fen"] == second_tomato["unit_price_fen"] * second_tomato["quantity"]
    assert indexed_client.get("/api/v1/cart").json() == first_cart

    second_confirmation = indexed_client.post(
        f"/api/v1/guide/tasks/{rebuilt['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": second_revision["plan_id"],
            "plan_version": second_revision["plan_version"],
            "expected_session_version": second_revision["session_version"],
            "expected_state_version": second_revision["state_version"],
            "selected_items": [{"sku_id": tomato["sku_id"], "quantity": second_tomato["quantity"]}],
        },
    )
    assert second_confirmation.status_code == 200, second_confirmation.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert {row["sku_id"] for row in cart["items"]} == {egg["sku_id"], tomato["sku_id"]}

    checkout = indexed_client.post(
        "/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}
    )
    assert checkout.status_code == 200, checkout.json()
    result = checkout.json()
    order = result["order"]
    assert order["status"] == "paid"
    assert order["total_fen"] == cart["total_price_fen"]
    assert sorted(
        (row["sku_id"], row["product_name"], row["quantity"], row["unit_price_fen"])
        for row in order["items"]
    ) == sorted(
        (row["sku_id"], row["name"], row["quantity"], row["unit_price_fen"])
        for row in cart["items"]
    )
    assert result["cart"]["items"] == []
    assert indexed_client.get("/api/v1/cart").json() == result["cart"]
    assert indexed_client.get("/api/v1/orders").json()["items"] == [order]
    assert indexed_client.get(f"/api/v1/orders/{order['order_id']}").json() == order

    def answer_unselected_order_query(**kwargs):
        assert {tool["function"]["name"] for tool in kwargs["tools"]} == {
            "search_after_sales_policy"
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="请选择订单后再查询。",
            tool_calls=[],
        ))])

    monkeypatch.setattr(
        "mercury.llm.OpenAI",
        lambda **_settings: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=answer_unselected_order_query))
        ),
    )
    mercury_session = indexed_client.post("/api/v1/mercury/sessions").json()
    mercury_id = mercury_session["session_id"]
    unselected = indexed_client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/turns/stream",
        json={"message": "这一单买了什么？", "request_id": f"demo-unselected-{run}"},
    )
    assert unselected.status_code == 200, unselected.text
    unselected_events = [
        json.loads(line[6:]) for line in unselected.text.splitlines() if line.startswith("data: ")
    ]
    assert next(row["items"] for row in unselected_events if "items" in row) == [order]
    assert "请选择" in next(row["final_text"] for row in unselected_events if "final_text" in row)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()

    def create(**kwargs):
        assert kwargs["model"] == "controlled-mercury"
        if kwargs["messages"][-1]["role"] != "tool":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="", tool_calls=[SimpleNamespace(
                    id="demo-order-read",
                    function=SimpleNamespace(
                        name="get_order_details",
                        arguments=json.dumps({"order_id": order["order_id"]}),
                    ),
                )],
            ))])
        facts = json.loads(kwargs["messages"][-1]["content"])
        assert facts["ok"] is True
        assert facts["data"]["order_id"] == order["order_id"]
        assert facts["data"]["total"] == f"{order['total_fen'] / 100:.2f}"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=f"{order['order_id']} 的成交总额为{facts['data']['total']}元，模拟订单未发货。",
            tool_calls=[],
        ))])

    def fake_openai(**settings):
        assert settings["base_url"] == "http://controlled-mercury.invalid/v1"
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

    monkeypatch.setattr("mercury.llm.OpenAI", fake_openai)
    selected = indexed_client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/order", json={"order_id": order["order_id"]}
    )
    assert selected.status_code == 200, selected.json()
    assert selected.json() == {"session_id": mercury_id, "order": order}
    queried = indexed_client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/turns/stream",
        json={"message": "只查询这一单买了什么，不申请售后。", "request_id": f"demo-query-{run}"},
    )
    assert queried.status_code == 200, queried.text
    queried_events = [
        json.loads(line[6:]) for line in queried.text.splitlines() if line.startswith("data: ")
    ]
    assert order["order_id"] in next(row["final_text"] for row in queried_events if "final_text" in row)
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0
    assert indexed_client.cookies.get("sg_owner_id") == owner

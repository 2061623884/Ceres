"""Opt-in two-run live Ceres V2 purchase, history, order and Mercury journey."""

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core import database as db_module
from app.core.config import get_settings
from app.services.retrieval_index import load_index
from support import create_session, send_turn
from support.v2_fixture import source_database_path


pytestmark = pytest.mark.skipif(
    os.environ.get("CERES_LIVE_V2_DEMO") != "1",
    reason="real-model integrated demo is explicitly invoked",
)


@pytest.mark.parametrize("run", [1, 2])
def test_live_v2_purchase_history_checkout_and_mercury_journey(client, run):
    settings = get_settings()
    assert settings.llm_mode == "live" and settings.business_data_mode == "demo"
    assert settings.llm_model.lower() == "qwen3.8-27b"
    assert settings.memory_model.lower() == "qwen3.8-27b"
    assert settings.retrieval_mode == "hybrid" and settings.retrieval_index_dir
    index = load_index(settings.root_dir / Path(settings.retrieval_index_dir))
    assert index.has_vectors()
    index_version = index.version
    embedding_model = index.embedding_contract["model"]
    index.close()
    run_info = {
        "run": run,
        "mode": "live",
        "llm_model": settings.llm_model,
        "memory_model": settings.memory_model,
        "retrieval_mode": settings.retrieval_mode,
        "index_version": index_version,
        "embedding_model": embedding_model,
    }

    preference = "我平时做番茄炒蛋喜欢清淡少盐"
    first_session = create_session(client)
    started = time.monotonic()
    saved = send_turn(client, first_session, f"请记住：{preference}")
    elapsed = time.monotonic() - started
    print(json.dumps({**run_info, "turn": "save_explicit_memory", "input": f"请记住：{preference}",
                      "elapsed_ms": round(elapsed * 1000), "reply": saved["message"],
                      "actions": saved["action_results"],
                      "versions": {"session": saved["session_version"], "state": saved["state_version"]}},
                     ensure_ascii=False))
    assert elapsed <= 15
    assert saved["answer_status"] == "accepted"
    saved_records = next(row for row in saved["action_results"] if row["type"] == "memory")["records"]
    assert any(row["source"] == "explicit" and "少盐" in row["content"] and "番茄炒蛋" in row["content"] for row in saved_records)

    started = time.monotonic()
    first = send_turn(client, first_session, "今晚四个人自己做番茄炒蛋")
    elapsed = time.monotonic() - started
    print(json.dumps({**run_info, "turn": "prepare_first_plan_raw", "elapsed_ms": round(elapsed * 1000), "result": first}, ensure_ascii=False))
    assert first["plan"] is not None, first
    first_plan = first["plan"]
    print(json.dumps({**run_info, "turn": "prepare_first_plan", "input": "今晚四个人自己做番茄炒蛋",
                      "elapsed_ms": round(elapsed * 1000), "reply": first["message"],
                      "actions": first["action_results"],
                      "versions": {"task_id": first["task_id"], "plan_id": first_plan["plan_id"],
                                   "plan": first_plan["plan_version"], "session": first["session_version"],
                                   "state": first["state_version"]}}, ensure_ascii=False))
    assert elapsed <= 15
    assert first["answer_status"] == "awaiting_confirmation"
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
    assert client.get("/api/v1/cart").json()["items"] == []

    egg = next(row for row in first_plan["items"] if row["sku_id"] == "demo:eggs-fresh-6pack")
    tomato = next(row for row in first_plan["items"] if row["sku_id"] == "demo:tomato-fresh-500g")
    started = time.monotonic()
    first_revision_response = client.post(
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
    print(json.dumps({**run_info, "action": "revise_first_selection",
                      "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "response": first_revision,
                      "versions": {"plan": first_revision["plan_version"],
                                   "session": first_revision["session_version"],
                                   "state": first_revision["state_version"]}}, ensure_ascii=False))
    assert first_revision["selected_total_fen"] == egg["unit_price_fen"] * egg["quantity"]
    assert client.get("/api/v1/cart").json()["items"] == []

    started = time.monotonic()
    first_confirmation = client.post(
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
    first_cart = client.get("/api/v1/cart").json()
    print(json.dumps({**run_info, "action": "confirm_first_selection",
                      "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "response": first_confirmation.json(),
                      "versions": {"cart": first_cart["version"]}}, ensure_ascii=False))
    assert [(row["sku_id"], row["quantity"]) for row in first_cart["items"]] == [
        (egg["sku_id"], egg["quantity"])
    ]

    second_session = create_session(client)
    started = time.monotonic()
    found = send_turn(client, second_session, "查询我之前的番茄炒蛋方案")
    elapsed = time.monotonic() - started
    print(json.dumps({**run_info, "turn": "read_history", "input": "查询我之前的番茄炒蛋方案",
                      "elapsed_ms": round(elapsed * 1000), "reply": found["message"],
                      "actions": found["action_results"],
                      "versions": {"session": found["session_version"], "state": found["state_version"]}},
                     ensure_ascii=False))
    assert elapsed <= 15
    assert found["answer_status"] == "accepted"
    assert first_revision["plan_id"] in found["message"]
    assert found["plan"] is None
    assert client.get("/api/v1/cart").json() == first_cart

    repurchase_message = "参考上次方案，但按今天四人份重新配番茄炒蛋清单，不恢复旧清单"
    started = time.monotonic()
    rebuilt = send_turn(client, second_session, repurchase_message, found)
    elapsed = time.monotonic() - started
    print(json.dumps({**run_info, "turn": "prepare_repurchase_raw", "elapsed_ms": round(elapsed * 1000), "result": rebuilt}, ensure_ascii=False))
    assert rebuilt["plan"] is not None, rebuilt
    second_plan = rebuilt["plan"]
    print(json.dumps({**run_info, "turn": "prepare_repurchase", "input": repurchase_message,
                      "elapsed_ms": round(elapsed * 1000), "reply": rebuilt["message"],
                      "actions": rebuilt["action_results"],
                      "versions": {"task_id": rebuilt["task_id"], "plan_id": second_plan["plan_id"],
                                   "plan": second_plan["plan_version"], "session": rebuilt["session_version"],
                                   "state": rebuilt["state_version"]}}, ensure_ascii=False))
    assert elapsed <= 15
    assert rebuilt["answer_status"] == "awaiting_confirmation"
    assert rebuilt["task_id"] != first["task_id"]
    assert second_plan["plan_id"] != first_revision["plan_id"]
    assert second_plan["targets"][0]["people"] == 4
    assert client.get("/api/v1/cart").json() == first_cart

    second_tomato = next(row for row in second_plan["items"] if row["sku_id"] == tomato["sku_id"])
    started = time.monotonic()
    second_revision_response = client.post(
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
    print(json.dumps({**run_info, "action": "revise_repurchase_selection",
                      "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "response": second_revision,
                      "versions": {"plan": second_revision["plan_version"],
                                   "session": second_revision["session_version"],
                                   "state": second_revision["state_version"]}}, ensure_ascii=False))
    assert second_revision["selected_total_fen"] == second_tomato["unit_price_fen"] * second_tomato["quantity"]
    assert client.get("/api/v1/cart").json() == first_cart

    started = time.monotonic()
    second_confirmation = client.post(
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
    cart = client.get("/api/v1/cart").json()
    print(json.dumps({**run_info, "action": "confirm_repurchase_selection",
                      "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "response": second_confirmation.json(), "versions": {"cart": cart["version"]}},
                     ensure_ascii=False))
    assert {row["sku_id"] for row in cart["items"]} == {egg["sku_id"], tomato["sku_id"]}

    started = time.monotonic()
    checkout = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]})
    assert checkout.status_code == 200, checkout.json()
    result = checkout.json()
    order = result["order"]
    print(json.dumps({**run_info, "action": "checkout", "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "order": order, "versions": {"cart_before": cart["version"],
                                                     "cart_after": result["cart"]["version"]}},
                     ensure_ascii=False))
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
    assert client.get("/api/v1/orders").json()["items"] == [order]

    mercury_session = client.post("/api/v1/mercury/sessions").json()
    assert mercury_session["selected_order_id"] is None
    mercury_id = mercury_session["session_id"]
    started = time.monotonic()
    unselected = client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/turns/stream",
        json={"message": "这一单买了什么？", "request_id": f"live-unselected-{run}"},
    )
    elapsed = time.monotonic() - started
    assert unselected.status_code == 200, unselected.text
    unselected_payloads = [
        json.loads(line[6:]) for line in unselected.text.splitlines() if line.startswith("data: ")
    ]
    print(json.dumps({**run_info, "turn": "mercury_without_selection",
                      "input": "这一单买了什么？", "elapsed_ms": round(elapsed * 1000),
                      "reply": next(row["final_text"] for row in unselected_payloads if "final_text" in row),
                      "orders": next(row["items"] for row in unselected_payloads if "items" in row)},
                     ensure_ascii=False))
    assert elapsed <= 15
    assert next(row["items"] for row in unselected_payloads if "items" in row) == [order]

    selected = client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/order", json={"order_id": order["order_id"]}
    )
    assert selected.status_code == 200, selected.json()
    assert selected.json() == {"session_id": mercury_id, "order": order}
    read_only_message = "请告诉我这笔订单买了什么商品、成交总额和当前状态，只查询，不申请退款或退货。"
    started = time.monotonic()
    queried = client.post(
        f"/api/v1/mercury/sessions/{mercury_id}/turns/stream",
        json={"message": read_only_message, "request_id": f"live-order-query-{run}"},
    )
    elapsed = time.monotonic() - started
    assert queried.status_code == 200, queried.text
    queried_payloads = [
        json.loads(line[6:]) for line in queried.text.splitlines() if line.startswith("data: ")
    ]
    answer = next(row["final_text"] for row in queried_payloads if "final_text" in row)
    print(json.dumps({**run_info, "turn": "mercury_selected_order_query", "input": read_only_message,
                      "elapsed_ms": round(elapsed * 1000), "reply": answer,
                      "actions": queried_payloads,
                      "versions": {"selected_order_id": selected.json()["order"]["order_id"]}},
                     ensure_ascii=False))
    assert elapsed <= 15
    assert order["order_id"] in answer
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0

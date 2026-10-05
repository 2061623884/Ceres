"""Historical plans are references, never restored purchase authority."""

import json
import uuid

import pytest

from app.core import database as db_module
from app.models.conversation import PlanSnapshot
from app.models.store import Offer

from support import create_session, send_turn
from support.semantic_agent import Continuation, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_history_in_new_session_has_real_source_and_rebuilds_new_plan(indexed_client, semantic_provider, run):
    semantic_provider([request_new("dish", "番茄炒蛋", people=2, mode="self_cook")])
    old_sid = create_session(indexed_client)
    original = send_turn(indexed_client, old_sid, "两个人自己做番茄炒蛋")
    original_plan = original["plan"]
    revision = indexed_client.post(
        f"/api/v1/guide/tasks/{original['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": original["session_version"],
              "expected_state_version": original["state_version"], "base_plan_id": original_plan["plan_id"],
              "base_plan_version": original_plan["plan_version"], "coverage_intent": "partial_ok",
              "items": [{"sku_id": i["sku_id"], "quantity": i["quantity"], "selected": i["role"] == "pantry"}
                        for i in original_plan["items"]]},
    )
    assert revision.status_code == 200, revision.json()
    source = revision.json()
    old_view = indexed_client.get(f"/api/v1/guide/sessions/{old_sid}").json()["plan"]
    with db_module.SessionLocal() as db:
        frozen_json = db.get(PlanSnapshot, (source["plan_id"], source["plan_version"])).plan_json
        db.query(Offer).filter_by(sku_id="demo:tomato-fresh-500g").update({Offer.price_fen: 840})
        db.commit()

    def historical_answer(request):
        history = next(row for row in request["query_results"] if row["kind"] == "history")
        row = history["plans"][0]
        assert row["plan_id"] == source["plan_id"]
        assert row["task_id"] == original["task_id"]
        assert row["plan_version"] == source["plan_version"]
        assert row["source_complete"] is True
        target = row["targets"][0]
        assert target["name"] == "番茄炒蛋"
        return {"reply": f"历史方案 {row['plan_id']} 是番茄炒蛋；本次需重新生成清单并确认。",
                "display_refs": [target["ref"]]}

    semantic_provider([{"reads": [{"kind": "history"}]}, Continuation(historical_answer),
                       request_new("dish", "番茄炒蛋", people=4, mode="self_cook",
                                   constraints={"budget_yuan": 50})])
    sid = create_session(indexed_client)
    found = send_turn(indexed_client, sid, "上次做的是什么？")
    assert source["plan_id"] in found["message"]
    assert found["plan"] is None
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    rebuilt = send_turn(indexed_client, sid, "就这个番茄炒蛋，这次四人份，预算50元，自己做", found)
    assert rebuilt["task_id"] != original["task_id"]
    assert rebuilt["plan"]["plan_id"] != source["plan_id"]
    assert rebuilt["plan"]["targets"][0]["people"] == 4
    assert all(i["selected"] for i in rebuilt["plan"]["items"] if i["role"] == "required")
    assert all(not i["selected"] for i in rebuilt["plan"]["items"] if i["role"] == "pantry")
    tomato = next(i for i in rebuilt["plan"]["items"] if i["sku_id"] == "demo:tomato-fresh-500g")
    assert tomato["unit_price_fen"] == 840 and tomato["quantity"] == 2
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    assert indexed_client.get(f"/api/v1/guide/sessions/{old_sid}").json()["plan"] == old_view
    with db_module.SessionLocal() as db:
        assert db.get(PlanSnapshot, (source["plan_id"], source["plan_version"])).plan_json == frozen_json
    plan = rebuilt["plan"]
    egg = next(i for i in plan["items"] if i["sku_id"] == "demo:eggs-fresh-6pack")
    revised = indexed_client.post(
        f"/api/v1/guide/tasks/{rebuilt['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": rebuilt["session_version"],
              "expected_state_version": rebuilt["state_version"], "base_plan_id": plan["plan_id"],
              "base_plan_version": plan["plan_version"], "coverage_intent": "partial_ok",
              "items": [{"sku_id": i["sku_id"], "quantity": i["quantity"], "selected": i["sku_id"] == egg["sku_id"]}
                        for i in plan["items"]]},
    )
    assert revised.status_code == 200, revised.json()
    chosen = revised.json()
    assert chosen["selected_total_fen"] == egg["unit_price_fen"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    confirmed = indexed_client.post(
        f"/api/v1/guide/tasks/{rebuilt['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": chosen["plan_id"], "plan_version": chosen["plan_version"],
              "expected_session_version": chosen["session_version"], "expected_state_version": chosen["state_version"],
              "selected_items": [{"sku_id": egg["sku_id"], "quantity": 1}]},
    )
    assert confirmed.status_code == 200, confirmed.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(i["sku_id"], i["quantity"]) for i in cart["items"]] == [(egg["sku_id"], 1)]
    assert cart["total_price_fen"] == chosen["selected_total_fen"]


@pytest.mark.parametrize("run", [1, 2])
def test_product_history_quantity_is_verified_and_current_quantity_wins(indexed_client, semantic_provider, run):
    semantic_provider([request_new("product", "新鲜鸡蛋 6枚装")])
    old_sid = create_session(indexed_client)
    original = send_turn(indexed_client, old_sid, "选新鲜鸡蛋6枚装，清单中再改为三盒")
    source_id = original["plan"]["plan_id"]
    revised = indexed_client.post(
        f"/api/v1/guide/tasks/{original['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": original["session_version"],
              "expected_state_version": original["state_version"], "base_plan_id": source_id,
              "base_plan_version": original["plan"]["plan_version"], "coverage_intent": "full",
              "items": [{"sku_id": "demo:eggs-fresh-6pack", "quantity": 3, "selected": True}]},
    )
    assert revised.status_code == 200, revised.json()

    def answer(request):
        row = request["query_results"][0]["plans"][0]
        target = row["targets"][0]
        assert row["plan_id"] == source_id
        assert target["historical_items"] == [{"sku_id": "demo:eggs-fresh-6pack", "quantity": 3,
                                               "unit_price_fen": 980, "shared": False}]
        return {"reply": f"方案 {source_id} 曾选三盒鸡蛋，需按本次条件重新配货。", "display_refs": [target["ref"]]}

    def choose(request):
        target = request["candidates"]["products"][0]
        return request_new("product", target["name"], ref=target["ref"], quantity=2)

    semantic_provider([{"reads": [{"kind": "history", "topic": source_id}]}, Continuation(answer), choose])
    sid = create_session(indexed_client)
    found = send_turn(indexed_client, sid, f"查历史方案{source_id}")
    rebuilt = send_turn(indexed_client, sid, "这次只买两盒", found)
    assert rebuilt["task_id"] != original["task_id"]
    assert [(i["sku_id"], i["quantity"]) for i in rebuilt["plan"]["items"]] == [("demo:eggs-fresh-6pack", 2)]
    assert rebuilt["plan"]["selected_total_fen"] == 1960
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_history_is_owner_scoped_and_missing_source_does_not_guess(indexed_client, semantic_provider, run):
    semantic_provider([request_new("dish", "番茄炒蛋", people=2, mode="self_cook")])
    old_sid = create_session(indexed_client)
    original = send_turn(indexed_client, old_sid, "两人份番茄炒蛋")
    source_id = original["plan"]["plan_id"]
    with db_module.SessionLocal() as db:
        snap = db.get(PlanSnapshot, (source_id, original["plan"]["plan_version"]))
        legacy = json.loads(snap.plan_json)
        del legacy["targets"]
        snap.plan_json = json.dumps(legacy)
        db.commit()

    def incomplete(request):
        row = request["query_results"][0]["plans"][0]
        assert row["plan_id"] == source_id and row["source_complete"] is False
        assert row["targets"] == []
        return {"reply": "这个历史来源缺少结构化菜品，请告诉我这次想买什么。", "display_refs": []}

    semantic_provider([{"reads": [{"kind": "history", "topic": source_id}]}, Continuation(incomplete)])
    sid = create_session(indexed_client)
    missing = send_turn(indexed_client, sid, "按上次的买")
    assert missing["plan"] is None and "缺少" in missing["message"]
    indexed_client.cookies.clear()

    def empty(request):
        facts = request["query_results"][0]
        assert facts["kind"] == "history" and facts["plans"] == [] and facts["empty"] is True
        return {"reply": "未找到属于你的历史方案，请提供本次需求。", "display_refs": []}

    semantic_provider([{"reads": [{"kind": "history", "topic": source_id}]}, Continuation(empty)])
    stranger_sid = create_session(indexed_client)
    refused = send_turn(indexed_client, stranger_sid, f"用历史方案{source_id}")
    assert refused["plan"] is None and "未找到" in refused["message"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("source_shape", ["missing_items", "shared_quantity", "null_association"])
def test_incomplete_product_history_asks_quantity_without_purchase_ref(indexed_client, semantic_provider, run, source_shape):
    semantic_provider([request_new("product", "新鲜鸡蛋 6枚装")])
    original = send_turn(indexed_client, create_session(indexed_client), "买鸡蛋6枚装")
    source_id = original["plan"]["plan_id"]
    with db_module.SessionLocal() as db:
        snap = db.get(PlanSnapshot, (source_id, original["plan"]["plan_version"]))
        legacy = json.loads(snap.plan_json)
        if source_shape == "missing_items":
            legacy["items"] = []
        elif source_shape == "shared_quantity":
            item = legacy["items"][0]
            item["contributions"] = [{"group_id": legacy["targets"][0]["group_id"]},
                                     {"group_id": "another-dish"}]
        else:
            legacy["targets"][0]["group_id"] = None
            legacy["items"][0]["group_id"] = None
            legacy["items"][0]["contributions"] = None
        snap.plan_json = json.dumps(legacy)
        db.commit()

    def clarify(request):
        row = request["query_results"][0]["plans"][0]
        assert row["source_complete"] is False
        assert all("ref" not in target for target in row["targets"])
        return {"reply": "历史商品缺少独立件数，请告诉我这次需要几盒鸡蛋。", "display_refs": []}

    semantic_provider([{"reads": [{"kind": "history", "topic": source_id}]}, Continuation(clarify)])
    sid = create_session(indexed_client)
    result = send_turn(indexed_client, sid, "照上次买鸡蛋")
    assert "几盒" in result["message"] and result["plan"] is None and result["task_id"] is None
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_historical_multi_dish_is_rebuilt_by_explicit_additions(indexed_client, semantic_provider, run):
    semantic_provider([request_new("dish", "番茄炒蛋", people=2, mode="self_cook"),
                       request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append")])
    old_sid = create_session(indexed_client)
    first = send_turn(indexed_client, old_sid, "两人份番茄炒蛋")
    original = send_turn(indexed_client, old_sid, "再加一人份番茄蛋汤", first)

    def answer(request):
        row = request["query_results"][0]["plans"][0]
        assert row["plan_id"] == original["plan"]["plan_id"]
        assert {t["name"] for t in row["targets"]} == {"番茄炒蛋", "番茄蛋汤"}
        assert all(i["shared"] for t in row["targets"] for i in t["historical_items"]
                   if i["sku_id"] == "demo:eggs-fresh-6pack")
        return {"reply": "历史方案有番茄炒蛋和番茄蛋汤，请逐项选择本次需要的菜。",
                "display_refs": [t["ref"] for t in row["targets"]]}

    semantic_provider([{"reads": [{"kind": "history", "topic": original["plan"]["plan_id"]}]}, Continuation(answer),
                       request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints={"budget_yuan": 50}),
                       request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append")])
    sid = create_session(indexed_client)
    found = send_turn(indexed_client, sid, "上次两道菜是什么？")
    rebuilt = send_turn(indexed_client, sid, "这次先做两人份番茄炒蛋，预算50元", found)
    appended = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", rebuilt)
    assert appended["task_id"] != original["task_id"]
    assert {t["name"] for t in appended["plan"]["targets"]} == {"番茄炒蛋", "番茄蛋汤"}
    assert appended["plan"]["selected_total_fen"] == 1660
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("condition", ["stock", "budget", "exclusion"])
def test_history_rebuild_obeys_current_supply_and_conditions(indexed_client, semantic_provider, run, condition):
    semantic_provider([request_new("dish", "番茄炒蛋", people=2, mode="self_cook")])
    old_sid = create_session(indexed_client)
    original = send_turn(indexed_client, old_sid, "两人份番茄炒蛋")
    source_id = original["plan"]["plan_id"]
    if condition == "stock":
        with db_module.SessionLocal() as db:
            db.query(Offer).filter(Offer.sku_id.in_(["demo:eggs-fresh-6pack", "demo:eggs-10pack"])).update(
                {Offer.available_qty: 0}, synchronize_session=False,
            )
            db.commit()
    conditions = {"budget_yuan": 1} if condition == "budget" else {"excluded_ingredients": ["鸡蛋"]} if condition == "exclusion" else {}

    def answer(request):
        target = request["query_results"][0]["plans"][0]["targets"][0]
        return {"reply": f"历史方案{source_id}是番茄炒蛋，请明确本次条件。", "display_refs": [target["ref"]]}

    semantic_provider([{"reads": [{"kind": "history", "topic": source_id}]}, Continuation(answer),
                       request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints=conditions)])
    sid = create_session(indexed_client)
    found = send_turn(indexed_client, sid, "查上次的番茄炒蛋")
    attempt = send_turn(indexed_client, sid, "按上次的菜，本次条件已明确", found)
    assert attempt["plan"] is None, attempt
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    if condition == "stock":
        assert any(q["slot"] == "supply_gap_choice" and "鸡蛋" in q["question"]
                   for q in attempt["pending_clarifications"]), attempt
    elif condition == "budget":
        assert "预算" in attempt["message"], attempt
    else:
        assert "鸡蛋" in attempt["message"], attempt

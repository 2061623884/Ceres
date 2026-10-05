"""Explicit dishes share compatible demand before purchasing whole packs."""

import uuid

import pytest

from support import create_session, send_turn
from support.semantic_agent import lookup_then_add_id, request_amend, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_shared_recipe_demand_to_confirmed_cart(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints={"budget_yuan": 100}),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋，预算100元，自己做")
    appended = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", first)
    plan = appended["plan"]
    assert plan is not None, appended
    tomato = next(i for i in plan["items"] if i["sku_id"] == "demo:tomato-fresh-500g")
    egg = next(i for i in plan["items"] if i["sku_id"] == "demo:eggs-fresh-6pack")
    assert tomato["quantity"] == 1
    assert egg["quantity"] == 1
    assert [c["requirement"]["quantity"] for c in tomato["contributions"]] == [300, 125]
    assert [c["requirement"]["quantity"] for c in egg["contributions"]] == [3, 1]
    assert {t["target_id"]: t["people"] for t in plan["targets"]} == {
        "dish-fanqie-chao-dan": 2, "dish-fanqie-dan-tang": 1,
    }
    assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
    assert plan["selected_total_fen"] == plan["outstanding_total_fen"] == 1660
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    confirmed = indexed_client.post(
        f"/api/v1/guide/tasks/{appended['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": appended["state_version"],
              "expected_session_version": appended["session_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                 for i in plan["items"] if i["selected"]]},
    )
    assert confirmed.status_code == 200, confirmed.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        "demo:tomato-fresh-500g": 1, "demo:eggs-fresh-6pack": 1,
    }
    assert cart["total_price_fen"] == 1660


@pytest.mark.parametrize("run", [1, 2])
def test_scoped_people_remove_and_direct_pack_remain_separate(indexed_client, semantic_provider, run):
    def resize_first(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-chao-dan")
        return request_amend(focus=group["ref"], changes={"set": {"people": 4}})

    def remove_soup(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-dan-tang")
        return request_amend(focus=group["ref"], name=group["name"], op="remove")

    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook"),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"),
        resize_first, remove_soup,
        *lookup_then_add_id("product", "新鲜鸡蛋 6枚装", "demo:eggs-fresh-6pack", relation="append"),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋")
    two = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", first)
    resized = send_turn(indexed_client, sid, "只把番茄炒蛋改为四人份", two)
    assert {t["target_id"]: t["people"] for t in resized["plan"]["targets"]} == {
        "dish-fanqie-chao-dan": 4, "dish-fanqie-dan-tang": 1,
    }
    assert resized["plan"]["selected_total_fen"] == 3320
    removed = send_turn(indexed_client, sid, "不做番茄蛋汤了，移除这道菜", resized)
    assert removed["plan"] is not None, removed
    assert len(removed["plan"]["targets"]) == 1
    assert removed["plan"]["selected_total_fen"] == 2340
    direct = send_turn(indexed_client, sid, "另买一盒6枚装鸡蛋", removed)
    egg = next(i for i in direct["plan"]["items"] if i["sku_id"] == "demo:eggs-fresh-6pack")
    assert egg["quantity"] == 2
    assert {c["requirement"]["unit"] for c in egg["contributions"]} == {"pc", "件"}
    assert direct["plan"]["selected_total_fen"] == 3320
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_append_keeps_user_quantity_and_selection(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook"),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋")
    plan = first["plan"]
    edits = [{"sku_id": i["sku_id"],
              "quantity": 3 if i["sku_id"] == "demo:tomato-fresh-500g" else i["quantity"],
              "selected": False if i["sku_id"] == "demo:eggs-fresh-6pack" else i["selected"]}
             for i in plan["items"]]
    revision = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": first["session_version"],
              "expected_state_version": first["state_version"], "base_plan_id": plan["plan_id"],
              "base_plan_version": plan["plan_version"], "coverage_intent": "partial_ok", "items": edits},
    )
    assert revision.status_code == 200, revision.json()
    current = {**first, **revision.json()}
    appended = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", current)
    by_sku = {i["sku_id"]: i for i in appended["plan"]["items"]}
    assert (by_sku["demo:tomato-fresh-500g"]["quantity"], by_sku["demo:tomato-fresh-500g"]["quantity_source"]) == (3, "user")
    assert by_sku["demo:eggs-fresh-6pack"]["selected"] is False
    assert appended["plan"]["selected_total_fen"] == 2040
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_shared_demand_keeps_already_added_packs(indexed_client, semantic_provider, run):
    def resize_first(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-chao-dan")
        return request_amend(focus=group["ref"], changes={"set": {"people": 3}})

    def remove_first(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-chao-dan")
        return request_amend(focus=group["ref"], name=group["name"], op="remove")

    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook"),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"),
        resize_first, remove_first,
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋")
    added = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/items/demo:tomato-fresh-500g/add",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"request_id": str(uuid.uuid4()), "quantity": 1,
              "expected_state_version": first["state_version"], "expected_session_version": first["session_version"]},
    )
    assert added.status_code == 200, added.json()
    current = {**first, **added.json()}
    two = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", current)
    tomato = next(i for i in two["plan"]["items"] if i["sku_id"] == "demo:tomato-fresh-500g")
    assert (tomato["quantity"], tomato["added_quantity"], tomato["remaining_quantity"]) == (1, 1, 0)
    resized = send_turn(indexed_client, sid, "番茄炒蛋改为三人份", two)
    tomato = next(i for i in resized["plan"]["items"] if i["sku_id"] == "demo:tomato-fresh-500g")
    assert (tomato["quantity"], tomato["added_quantity"], tomato["remaining_quantity"]) == (2, 1, 1)
    removed = send_turn(indexed_client, sid, "移除番茄炒蛋，只做番茄蛋汤", resized)
    assert removed["plan"] is not None, removed
    tomato = next(i for i in removed["plan"]["items"] if i["sku_id"] == "demo:tomato-fresh-500g")
    assert (tomato["quantity"], tomato["added_quantity"], tomato["remaining_quantity"]) == (1, 1, 0)
    plan = removed["plan"]
    result = indexed_client.post(
        f"/api/v1/guide/tasks/{removed['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": removed["state_version"], "expected_session_version": removed["session_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                 for i in plan["items"] if i["selected"] and i["remaining_quantity"]]},
    )
    assert result.status_code == 200, result.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        "demo:tomato-fresh-500g": 1, "demo:eggs-fresh-6pack": 1,
    }
    assert cart["total_price_fen"] == 1660


@pytest.mark.parametrize("run", [1, 2])
def test_shared_demand_preserves_whole_plan_constraints(indexed_client, semantic_provider, run):
    def resize_soup(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-dan-tang")
        return request_amend(focus=group["ref"], changes={"set": {"people": 4}})

    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook",
                    constraints={"budget_yuan": 20, "excluded_ingredients": ["猪肉"]}),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"),
        resize_soup,
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋，预算20元，不吃猪肉")
    two = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", first)
    assert two["plan"]["selected_total_fen"] == 1660
    before = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    refused = send_turn(indexed_client, sid, "只把番茄蛋汤改为四人份", two)
    assert refused["plan_effect"] == "keep", refused
    after = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert after["plan"] == before["plan"]
    assert after["constraints_summary"]["budget_fen"] == 2000
    assert after["constraints_summary"]["excluded_ingredients"] == before["constraints_summary"]["excluded_ingredients"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

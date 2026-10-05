"""V2 servings at the public guide, selection and confirmation interfaces."""

import uuid

import pytest

from app.services.template_matcher import scale_items
from support import create_session, send_turn
from support.semantic_agent import request_amend, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_single_dish_people_revision_selection_and_confirmation(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints={"excluded_ingredients": ["猪肉"]}),
        request_amend(changes={"set": {"people": 3}}),
        request_amend(changes={"set": {"people": 4}}),
    ])
    sid = create_session(indexed_client)
    assert indexed_client.get("/api/v1/products?page_size=500").json()["total"] == 65
    original = send_turn(indexed_client, sid, "两个人自己做番茄炒蛋，不吃猪肉")
    initial_constraints = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["constraints_summary"]
    assert initial_constraints["excluded_ingredients"]
    three = send_turn(indexed_client, sid, "改为三人份", original)
    three_egg = next(i for i in three["plan"]["items"] if i["requirement"]["ingredient_id"] == "egg")
    assert (three_egg["requirement"]["quantity"], three_egg["quantity"]) == (4.5, 1)
    resized = send_turn(indexed_client, sid, "改为四人份", three)
    plan = resized["plan"]
    tomato = next(i for i in plan["items"] if i["requirement"]["ingredient_id"] == "tomato")
    egg = next(i for i in plan["items"] if i["requirement"]["ingredient_id"] == "egg")
    assert (tomato["requirement"]["quantity"], tomato["quantity"], tomato["spec_quantity"]) == (600, 2, 500)
    assert (egg["requirement"]["quantity"], egg["quantity"], egg["spec_quantity"]) == (6, 1, 6)
    assert plan["plan_version"] == three["plan"]["plan_version"] + 1
    assert plan["selected_total_fen"] == 2340
    assert plan["targets"][0]["people"] == 4
    assert all(i["selected"] for i in plan["items"] if i["role"] == "required")
    assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

    edits = [{"sku_id": i["sku_id"], "quantity": i["quantity"], "selected": i["selected"]}
             for i in plan["items"]]
    edits[next(n for n, i in enumerate(plan["items"]) if i["sku_id"] == tomato["sku_id"])]["selected"] = False
    revision = indexed_client.post(
        f"/api/v1/guide/tasks/{resized['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": resized["session_version"],
              "expected_state_version": resized["state_version"], "base_plan_id": plan["plan_id"],
              "base_plan_version": plan["plan_version"], "coverage_intent": "partial_ok", "items": edits},
    )
    assert revision.status_code == 200, revision.json()
    revised = revision.json()
    assert revised["selected_total_fen"] == egg["unit_price_fen"]
    restored = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["plan"]["items"] == revised["items"]
    assert restored["constraints_summary"]["excluded_ingredients"] == initial_constraints["excluded_ingredients"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    confirmation = indexed_client.post(
        f"/api/v1/guide/tasks/{resized['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": revised["plan_id"], "plan_version": revised["plan_version"],
              "expected_session_version": revised["session_version"], "expected_state_version": revised["state_version"],
              "selected_items": [{"sku_id": egg["sku_id"], "quantity": 1}]},
    )
    assert confirmation.status_code == 200, confirmation.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(i["sku_id"], i["quantity"]) for i in cart["items"]] == [(egg["sku_id"], 1)]
    assert cart["total_price_fen"] == egg["unit_price_fen"]


@pytest.mark.parametrize("key,amount,expected", [
    ("quantity_g", 301, 451.5), ("quantity_ml", 301, 451.5), ("quantity_pc", 3, 4.5),
])
def test_servings_preserve_recipe_amount_before_package_rounding(key, amount, expected):
    assert scale_items([{"ingredient_id": "ingredient", key: amount}], 2, 3) == [
        {"ingredient_id": "ingredient", key: expected}
    ]


@pytest.mark.parametrize("run", [1, 2])
def test_people_change_keeps_the_existing_budget(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints={"budget_yuan": 20}),
        request_amend(changes={"set": {"people": 4}}),
    ])
    sid = create_session(indexed_client)
    original = send_turn(indexed_client, sid, "两个人做番茄炒蛋，预算20元")
    before = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    resized = send_turn(indexed_client, sid, "改为四人份", original)
    assert resized["plan_effect"] == "keep", resized
    restored = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["plan"] == before["plan"]
    assert restored["constraints_summary"]["budget_fen"] == 2000
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

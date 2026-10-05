"""Whole-package choices and honest supply adaptation through Guide APIs."""

import uuid

import pytest

from app.core import database as db_module
from app.models.store import Offer
from app.models.catalog import CatalogProduct
from support import create_session, send_turn
from support.semantic_agent import request_amend, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_recipe_selects_actual_whole_pack_price(indexed_client, semantic_provider, run):
    semantic_provider([request_new("dish", "番茄炒蛋", people=6, mode="self_cook",
                                   constraints={"budget_yuan": 100})])
    sid = create_session(indexed_client)
    prepared = send_turn(indexed_client, sid, "六人份番茄炒蛋，预算100元，自己做")
    plan = prepared["plan"]
    assert plan is not None, prepared
    eggs = [i for i in plan["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert [(i["sku_id"], i["quantity"]) for i in eggs] == [("demo:eggs-10pack", 1)]
    assert eggs[0]["requirement"]["quantity"] == 9
    assert (eggs[0]["spec_quantity"], eggs[0]["unit_price_fen"]) == (10, 1280)
    assert plan["selected_total_fen"] == 2640
    assert plan["coverage_mode"] == "full"
    assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    result = indexed_client.post(
        f"/api/v1/guide/tasks/{prepared['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": prepared["state_version"], "expected_session_version": prepared["session_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                 for i in plan["items"] if i["selected"]]},
    )
    assert result.status_code == 200, result.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        "demo:tomato-fresh-500g": 2, "demo:eggs-10pack": 1,
    }
    assert cart["total_price_fen"] == 2640


@pytest.mark.parametrize("run", [1, 2])
def test_same_ingredient_pack_combination_revision_and_confirmation(indexed_client, semantic_provider, run):
    with db_module.SessionLocal() as db:
        db.query(Offer).filter(Offer.sku_id.in_(["demo:eggs-fresh-6pack", "demo:eggs-10pack"])).update(
            {Offer.available_qty: 1}, synchronize_session=False,
        )
        db.commit()
    semantic_provider([request_new("dish", "番茄炒蛋", people=8, mode="self_cook",
                                   constraints={"budget_yuan": 100})])
    sid = create_session(indexed_client)
    prepared = send_turn(indexed_client, sid, "八人份番茄炒蛋，预算100元")
    plan = prepared["plan"]
    assert plan is not None, prepared
    eggs = [i for i in plan["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert {i["sku_id"]: i["quantity"] for i in eggs} == {
        "demo:eggs-fresh-6pack": 1, "demo:eggs-10pack": 1,
    }
    assert sum(i["requirement"]["quantity"] for i in eggs) == 12
    assert all(i["requirement"]["source"]["original_quantity"] == 12 for i in eggs)
    assert plan["selected_total_fen"] == 4300
    assert plan["coverage_mode"] == "full"
    for choose_ten in (False, True):
        revised = indexed_client.post(
            f"/api/v1/guide/tasks/{prepared['task_id']}/plan-revisions",
            json={"request_id": str(uuid.uuid4()), "expected_session_version": prepared["session_version"],
                  "expected_state_version": prepared["state_version"], "base_plan_id": plan["plan_id"],
                  "base_plan_version": plan["plan_version"], "coverage_intent": "full",
                  "items": [{"sku_id": i["sku_id"], "quantity": i["quantity"],
                             "selected": choose_ten if i["sku_id"] == "demo:eggs-10pack" else i["selected"]}
                            for i in plan["items"]]},
        )
        assert revised.status_code == 200, revised.json()
        assert revised.json()["can_confirm"] is choose_ten
        assert revised.json()["selected_total_fen"] == (4300 if choose_ten else 3020)
        assert indexed_client.get("/api/v1/cart").json()["items"] == []
        prepared = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
        plan = prepared["plan"]
        result = indexed_client.post(
            f"/api/v1/guide/tasks/{prepared['task_id']}/confirm",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
                  "expected_state_version": prepared["state_version"], "expected_session_version": prepared["session_version"],
                  "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                     for i in plan["items"] if i["selected"]]},
        )
        assert result.status_code == (200 if choose_ten else 422), result.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        "demo:tomato-fresh-500g": 3, "demo:eggs-fresh-6pack": 1, "demo:eggs-10pack": 1,
    }
    assert cart["total_price_fen"] == 4300


@pytest.mark.parametrize("run", [1, 2])
def test_shared_ingredient_reprices_total_demand_before_budget_check(indexed_client, semantic_provider, run):
    def remove_soup(request):
        group = next(g for g in request["current_plan"]["groups"] if g["group_id"] == "dish:dish-fanqie-dan-tang")
        return request_amend(focus=group["ref"], name=group["name"], op="remove")

    semantic_provider([
        request_new("dish", "番茄炒蛋", people=4, mode="self_cook", constraints={"budget_yuan": 30}),
        request_new("dish", "番茄蛋汤", people=1, mode="self_cook", relation="append"), remove_soup,
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "四人份番茄炒蛋，预算30元")
    assert first["plan"]["selected_total_fen"] == 2340
    two = send_turn(indexed_client, sid, "再加一人份番茄蛋汤", first)
    plan = two["plan"]
    assert plan is not None, two
    eggs = [i for i in plan["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert [(i["sku_id"], i["quantity"]) for i in eggs] == [("demo:eggs-10pack", 1)]
    assert [c["requirement"]["quantity"] for c in eggs[0]["contributions"]] == [6, 1]
    assert plan["selected_total_fen"] == 2640
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    removed = send_turn(indexed_client, sid, "移除番茄蛋汤", two)
    assert removed["plan"]["selected_total_fen"] == 2340
    eggs = [i for i in removed["plan"]["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert [(i["sku_id"], i["quantity"]) for i in eggs] == [("demo:eggs-fresh-6pack", 1)]
    assert indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["constraints_summary"]["budget_fen"] == 3000


@pytest.mark.parametrize("run", [1, 2])
def test_near_price_prefers_less_surplus(indexed_client, semantic_provider, run):
    with db_module.SessionLocal() as db:
        db.query(Offer).filter_by(sku_id="demo:eggs-10pack").update({Offer.price_fen: 960})
        db.commit()
    semantic_provider([request_new("dish", "番茄炒蛋", people=4, mode="self_cook")])
    prepared = send_turn(indexed_client, create_session(indexed_client), "四人份番茄炒蛋")
    eggs = [i for i in prepared["plan"]["items"] if i["requirement"]["ingredient_id"] == "egg"]
    # 980 <= 960 * 1.05: zero surplus wins over four unused eggs.
    assert [(i["sku_id"], i["quantity"]) for i in eggs] == [("demo:eggs-fresh-6pack", 1)]
    assert prepared["plan"]["selected_total_fen"] == 2340
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_unchecked_pack_does_not_replace_selected_pack_on_servings_change(
    indexed_client, semantic_provider, run,
):
    with db_module.SessionLocal() as db:
        db.query(Offer).filter(Offer.sku_id.in_(["demo:eggs-fresh-6pack", "demo:eggs-10pack"])).update(
            {Offer.available_qty: 1}, synchronize_session=False,
        )
        db.commit()

    def resize(request):
        group = request["current_plan"]["groups"][0]
        return request_amend(focus=group["ref"], name=group["name"], changes={"set": {"people": 4}})

    semantic_provider([request_new("dish", "番茄炒蛋", people=8, mode="self_cook"), resize])
    sid = create_session(indexed_client)
    prepared = send_turn(indexed_client, sid, "八人份番茄炒蛋")
    plan = prepared["plan"]
    revision = indexed_client.post(
        f"/api/v1/guide/tasks/{prepared['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": prepared["session_version"],
              "expected_state_version": prepared["state_version"], "base_plan_id": plan["plan_id"],
              "base_plan_version": plan["plan_version"], "coverage_intent": "full",
              "items": [{"sku_id": i["sku_id"], "quantity": i["quantity"],
                         "selected": False if i["sku_id"] == "demo:eggs-10pack" else i["selected"]}
                        for i in plan["items"]]},
    )
    assert revision.status_code == 200, revision.json()
    previous = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    resized = send_turn(indexed_client, sid, "改成四人份", previous)
    eggs = [i for i in resized["plan"]["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert [(i["sku_id"], i["quantity"], i["selected"]) for i in eggs] == [
        ("demo:eggs-fresh-6pack", 1, True),
    ]
    assert resized["plan"]["selected_total_fen"] == 2340
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("stock", [0, 1])
def test_supply_preview_preserves_old_plan_then_partial_confirmation(indexed_client, semantic_provider, stock, run):
    target = request_new("dish", "番茄炒蛋", people=8, mode="self_cook", relation="append")
    def partial(request):
        question = next(q for q in request["pending_clarifications"] if q["slot"] == "supply_gap_choice")
        return {**target, "resolved_questions": [question["question_id"]]}
    semantic_provider([request_new("dish", "番茄蛋汤", people=1, mode="self_cook"), target, partial])
    sid = create_session(indexed_client)
    original = send_turn(indexed_client, sid, "一人份番茄蛋汤")
    original_snapshot = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    with db_module.SessionLocal() as db:
        db.query(Offer).filter_by(sku_id="demo:eggs-fresh-6pack").update({Offer.available_qty: stock})
        db.query(Offer).filter_by(sku_id="demo:eggs-10pack").update({Offer.available_qty: 0})
        db.commit()
    preview = send_turn(indexed_client, sid, "再加八人份番茄炒蛋", original)
    assert preview["plan"] is None and preview["plan_effect"] == "keep", preview
    persisted = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert persisted["plan"] == original_snapshot
    question = next(q for q in preview["pending_clarifications"] if q["slot"] == "supply_gap_choice")
    assert "鸡蛋" in question["question"] and "番茄炒蛋" in question["question"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    chosen = send_turn(indexed_client, sid, "就为能买到的生成清单", preview)
    plan = chosen["plan"]
    assert plan is not None and plan["coverage_mode"] == "partial", chosen
    assert any(g["ingredient_id"] == "egg" for g in plan["gaps"])
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    result = indexed_client.post(
        f"/api/v1/guide/tasks/{chosen['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": chosen["state_version"], "expected_session_version": chosen["session_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                 for i in plan["items"] if i["selected"]]},
    )
    assert result.status_code == 200, result.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert cart["total_price_fen"] == plan["outstanding_total_fen"]
    assert "demo:eggs-10pack" not in {i["sku_id"] for i in cart["items"]}
    assert next((i["quantity"] for i in cart["items"] if i["sku_id"] == "demo:eggs-fresh-6pack"), 0) == stock
    assert indexed_client.get("/api/v1/products?page_size=500").json()["total"] == 65


@pytest.mark.parametrize("run", [1, 2])
def test_package_selection_respects_explicit_size_before_price(indexed_client, semantic_provider, run):
    with db_module.SessionLocal() as db:
        db.add(CatalogProduct(sku_id="v2:tomato-1kg", name="番茄 1kg", name_zh="番茄 1kg",
                              category_id="fresh", review_status="approved", ingredient_ids='["tomato"]',
                              spec_quantity=1, spec_unit="kg"))
        db.add(Offer(store_id="store-demo-01", sku_id="v2:tomato-1kg", price_fen=100,
                     available_qty=10, sellable=True))
        db.commit()
    semantic_provider([request_new("dish", "番茄炒蛋", people=6, mode="self_cook",
                                   constraints={"specification": {"size": "small"}})])
    prepared = send_turn(indexed_client, create_session(indexed_client), "六人份番茄炒蛋，全部小包装")
    # Eggs have no defined small-package threshold; use the public recipe service
    # below for this weight-only condition instead of inventing an egg threshold.
    assert prepared["plan"] is None
    from app.agent.state import Requirements
    from app.services.template_plan_service import TemplatePlanService
    from app.services.validation_context import ValidationContext
    with db_module.SessionLocal() as db:
        result = TemplatePlanService(db).validate_template_plan(
            {"dish_id": "dish-v2-tomato", "base_people": 2,
             "required_items": [{"ingredient_id": "tomato", "quantity_g": 300}]}, 6,
            ctx=ValidationContext.from_requirements(Requirements(specification={"size": "small"}),
                                                   store_id="store-demo-01", delivery_zone_id="zone-default"),
        )
    assert result["validation_status"] == "passed", result
    assert [(i["sku_id"], i["quantity"]) for i in result["items"]] == [("demo:tomato-fresh-500g", 2)]
    assert result["selected_total_fen"] == 1360


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("budget", [30, 100])
def test_package_selection_accounts_for_owner_cart_and_actual_budget(indexed_client, semantic_provider, budget, run):
    with db_module.SessionLocal() as db:
        db.query(Offer).filter_by(sku_id="demo:eggs-10pack").update({Offer.available_qty: 1})
        db.commit()
    existing = indexed_client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-10pack", "quantity": 1})
    assert existing.status_code == 200, existing.json()
    before = indexed_client.get("/api/v1/cart").json()
    semantic_provider([request_new("dish", "番茄炒蛋", people=6, mode="self_cook",
                                   constraints={"budget_yuan": budget})])
    sid = create_session(indexed_client)
    prepared = send_turn(indexed_client, sid, f"六人份番茄炒蛋，预算{budget}元")
    assert indexed_client.get("/api/v1/cart").json() == before
    if budget == 30:
        assert prepared["plan"] is None, prepared
        assert indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] is None
    else:
        assert prepared["plan"] is not None, prepared
        eggs = [i for i in prepared["plan"]["items"] if i["requirement"]["ingredient_id"] == "egg"]
        assert [(i["sku_id"], i["quantity"]) for i in eggs] == [("demo:eggs-fresh-6pack", 2)]
        assert prepared["plan"]["selected_total_fen"] == 3320
        assert prepared["plan"]["coverage_mode"] == "full"


@pytest.mark.parametrize("run", [1, 2])
def test_bought_spec_is_retained_while_uncovered_demand_uses_other_spec(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook"),
        request_amend(changes={"set": {"people": 6}}),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "两人份番茄炒蛋")
    with db_module.SessionLocal() as db:
        db.query(Offer).filter_by(sku_id="demo:eggs-fresh-6pack").update({Offer.available_qty: 1})
        db.commit()
    added = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/items/demo:eggs-fresh-6pack/add",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"request_id": str(uuid.uuid4()), "quantity": 1,
              "expected_state_version": first["state_version"], "expected_session_version": first["session_version"]},
    )
    assert added.status_code == 200, added.json()
    resized = send_turn(indexed_client, sid, "改为六人份", {**first, **added.json()})
    plan = resized["plan"]
    assert plan is not None, resized
    eggs = [i for i in plan["items"] if i["requirement"]["ingredient_id"] == "egg"]
    assert {i["sku_id"]: (i["quantity"], i["added_quantity"], i["remaining_quantity"])
            for i in eggs} == {"demo:eggs-fresh-6pack": (1, 1, 0), "demo:eggs-10pack": (1, 0, 1)}
    assert sum(i["requirement"]["quantity"] for i in eggs) == 9
    assert plan["coverage_mode"] == "full"
    assert plan["selected_total_fen"] == 3620 and plan["outstanding_total_fen"] == 2640
    assert {i["sku_id"]: i["quantity"] for i in indexed_client.get("/api/v1/cart").json()["items"]} == {"demo:eggs-fresh-6pack": 1}
    result = indexed_client.post(
        f"/api/v1/guide/tasks/{resized['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": resized["state_version"], "expected_session_version": resized["session_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                                 for i in plan["items"] if i["selected"] and i["remaining_quantity"]]},
    )
    assert result.status_code == 200, result.json()
    assert indexed_client.get("/api/v1/cart").json()["total_price_fen"] == 3620


@pytest.mark.parametrize("run", [1, 2])
def test_cart_occupied_supply_requires_partial_opt_in(indexed_client, semantic_provider, run):
    with db_module.SessionLocal() as db:
        db.query(Offer).filter_by(sku_id="demo:eggs-10pack").update({Offer.available_qty: 1})
        db.query(Offer).filter_by(sku_id="demo:eggs-fresh-6pack").update({Offer.available_qty: 0})
        db.commit()
    assert indexed_client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-10pack", "quantity": 1}).status_code == 200
    before = indexed_client.get("/api/v1/cart").json()
    semantic_provider([request_new("dish", "番茄炒蛋", people=6, mode="self_cook")])
    sid = create_session(indexed_client)
    preview = send_turn(indexed_client, sid, "六人份番茄炒蛋")
    assert preview["plan"] is None and preview["plan_effect"] == "keep", preview
    assert any(q["slot"] == "supply_gap_choice" and "鸡蛋" in q["question"] for q in preview["pending_clarifications"])
    assert indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == before

"""P0 partial plans: missing material, missing supply, unknown supply.

The approved contract (D2/D3/D7, see
``docs/plans/2026-09-19-purchase-intent-p0-implementation.md``):

* a dish/product/scenario with a supply gap is a *partial draft*, not a refusal;
* ``gaps`` is the structured authority and is never lost, even when nothing is
  buyable;
* unknown supply is reported as ``unknown`` — never dressed up as a stock-out,
  and never kept as a selectable row;
* a missing pack spec keeps the one-pack suggestion but is never ``full``;
* a stock shortfall prepares the verified addable count and keeps the shortfall;
* partial confirmation is allowed when a verified sellable row is selected, and
  the confirmation path still refuses to silently change quantities.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.catalog import CatalogProduct
from app.models.store import Offer
from app.services.plan_validator import PlanValidator
from app.services.shopping_plan_service import ShoppingPlanService
from support import post_turn


# --------------------------------------------------------------------- helpers


def create_session(client) -> str:
    return client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


def _db(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def confirm(client, body: dict, *, items=None, key: str | None = None):
    plan = body["plan"]
    payload = items if items is not None else [
        {"sku_id": row["sku_id"], "quantity": row["quantity"]}
        for row in plan["items"]
        if row.get("selected", True)
    ]
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
            "selected_items": payload,
        },
    )


def _add_synthetic_sku(db, sku_id: str, *, ingredient_ids: str, **product_kwargs):
    db.add(
        CatalogProduct(
            sku_id=sku_id,
            name=sku_id,
            name_zh=sku_id,
            category_id="demo",
            review_status="approved",
            ingredient_ids=ingredient_ids,
            **product_kwargs,
        )
    )
    db.commit()


def _core_requirement(requirement_id: str, ingredient_id: str) -> dict:
    return {
        "required_item_id": requirement_id,
        "ingredient_id": ingredient_id,
        "component_id": None,
        "name": ingredient_id,
        "quantity": None,
        "unit": None,
        "quantity_known": False,
        "requiredness": "core",
        "source": {"kind": "local_recipe", "ref": "dish-synthetic"},
    }


# ----------------------------------------------------------- dish / production


def test_dish_with_missing_main_ingredient_is_partial_and_confirmable(
    client, semantic_provider
):
    """三杯鸡 needs basil, which this store cannot sell: partial, not a refusal."""
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "三杯鸡", "dish-sanbei-ji", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃三杯鸡，2人").json()

    assert body["status"] == "awaiting_confirmation", body
    plan = body["plan"]
    assert plan is not None, body
    assert plan["coverage_mode"] == "partial", plan
    assert plan["coverage_intent"] == "partial_ok", plan

    missing = [g for g in plan["gaps"] if g["kind"] == "not_found"]
    assert missing, plan["gaps"]
    basil = next(g for g in missing if g["ingredient_id"] == "basil")
    assert basil["requiredness"] == "core", basil
    assert basil["name"], basil
    assert "无法配齐" in basil["message"], basil
    assert "没有找到" in basil["message"], basil
    assert "本店没有" not in basil["message"], basil
    assert basil["source"] == {"kind": "local_recipe", "ref": "dish-sanbei-ji"}, basil
    assert basil["required_item_id"] == "dish:dish-sanbei-ji#basil", basil
    assert basil["group_id"] == "dish:dish-sanbei-ji", basil
    assert basil["target_kind"] == "dish", basil

    # The resolvable rows are still there, each carrying its requirement/evidence.
    assert plan["items"], plan
    for row in plan["items"]:
        assert row["availability"] in ("available", "insufficient_stock"), row
        assert row["required_item_id"], row
        assert row["requirement"]["source"]["kind"] == "local_recipe", row
        assert row["evidence"]["sku_source"] == "store_offer", row
        assert row["evidence"]["quoted_at"], row
        assert row["evidence"]["data_mode"], row
        assert "不是外部实时库存源" in row["evidence"]["source_note"], row
    assert plan["can_confirm"] is True, plan

    result = confirm(client, body)
    assert result.status_code == 200, result.text
    cart_skus = {i["sku_id"] for i in client.get("/api/v1/cart").json()["items"]}
    assert {row["sku_id"] for row in plan["items"] if row["selected"]} <= cart_skus


def test_zero_sellable_row_is_a_clear_unconfirmable_plan_with_the_gap(
    client, semantic_provider
):
    """清炒豆芽 only needs bean sprout: nothing is buyable, but the gap survives."""
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "清炒豆芽", "dish-qingchao-douya", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃清炒豆芽，2人").json()

    plan = body["plan"]
    assert body["status"] == "awaiting_confirmation", body
    assert plan is not None, body
    gap = next(g for g in plan["gaps"] if g["ingredient_id"] == "bean_sprout")
    assert gap["kind"] == "not_found", gap
    assert gap["requiredness"] == "core", gap
    assert plan["coverage_mode"] == "uncovered", plan
    assert plan["can_confirm"] is False, plan
    # Not an empty silent failure: the reason is in the reply the shopper reads.
    assert "无法配齐" in body["message"], body["message"]

    refused = confirm(client, body)
    assert refused.status_code == 422, refused.text
    assert client.get("/api/v1/cart").json()["items"] == []


def test_product_out_of_stock_is_a_gap_and_never_confirmable(db_session):
    """A product the store cannot supply stays an honest, non-confirmable draft.

    (The retrieval layer already drops zero-stock products from model candidates,
    so this exercises the plan boundary where a live stock change lands.)
    """
    offer = (
        db_session.query(Offer)
        .filter_by(store_id="store-demo-01", sku_id="demo:cola-330ml")
        .one()
    )
    offer.available_qty = 0
    db_session.commit()
    service = ShoppingPlanService(db_session)
    result = service.build_product_plan("可乐", target_id="demo:cola-330ml")

    assert result["status"] == "ok", result
    gap = next(g for g in result["gaps"] if g["sku_id"] == "demo:cola-330ml")
    assert gap["kind"] == "out_of_stock", gap
    assert gap["available_quantity"] == 0, gap
    assert result["items"] == [], result["items"]
    assert result["coverage_mode"] == "uncovered", result
    assert result["can_confirm"] is False, result

    merged = service.merge_plan(
        None, result, group_id=result["group_id"], operation="replace"
    )
    assert merged["items"] == [], merged
    assert any(g["sku_id"] == "demo:cola-330ml" for g in merged["gaps"]), merged
    assert merged["coverage_mode"] == "uncovered", merged
    assert merged["can_confirm"] is False, merged


# ----------------------------------------------------------- supply / evidence


def test_missing_offer_is_unknown_not_out_of_stock(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    _add_synthetic_sku(db_session, "p0:no-offer", ingredient_ids='["chicken_wing"]')

    result = validator.check_constraints(
        [{"sku_id": "p0:no-offer", "quantity": 1, "role": "required"}],
        ["p0:no-offer"],
        coverage_intent="partial_ok",
    )
    assert result["validation_status"] == "passed", result
    gap = result["gaps"][0]
    assert gap["kind"] == "unknown", gap
    assert gap["unknown_of"] == "availability", gap
    assert gap["evidence"]["stock_verified"] is False, gap
    assert "no offer" in " ".join(gap["evidence"]["unknown_constraints"]), gap
    assert result["items"] == [], result
    assert result["coverage_mode"] == "uncovered", result
    assert result["can_confirm"] is False, result


def test_unsellable_sku_is_not_found_and_not_selectable(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    _add_synthetic_sku(db_session, "p0:unsold", ingredient_ids='["tofu"]')
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:unsold",
            price_fen=500,
            available_qty=5,
            sellable=False,
        )
    )
    db_session.commit()

    result = validator.check_constraints(
        [{"sku_id": "p0:unsold", "quantity": 1, "role": "required"}],
        ["p0:unsold"],
        coverage_intent="partial_ok",
    )
    gap = result["gaps"][0]
    assert gap["kind"] == "not_found", gap
    assert result["items"] == [], result
    assert result["can_confirm"] is False, result


def test_unknown_pack_spec_keeps_one_pack_but_is_never_full(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    _add_synthetic_sku(db_session, "p0:no-spec", ingredient_ids='["soy_sauce"]')
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:no-spec",
            price_fen=320,
            available_qty=5,
            sellable=True,
        )
    )
    db_session.commit()

    requirement = _core_requirement("dish:dish-synthetic#soy_sauce", "soy_sauce")
    result = validator.check_constraints(
        [
            {
                "sku_id": "p0:no-spec",
                "quantity": 1,
                "role": "required",
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "assumed_one",
            }
        ],
        ["p0:no-spec"],
        coverage_intent="partial_ok",
    )
    unknown = [
        gap for gap in result["gaps"] if gap["kind"] == "unknown" and gap["unknown_of"] == "quantity"
    ]
    assert unknown, result["gaps"]
    assert unknown[0]["requiredness"] == "core", unknown[0]
    assert "未核实" in unknown[0]["message"], unknown[0]
    row = result["items"][0]
    assert row["pack_source"] == "assumed_one", row
    assert row["requirement"]["quantity_known"] is False, row
    assert result["coverage_mode"] == "partial", result
    # One pack is a determined purchase, so it may still be confirmed partially.
    assert result["can_confirm"] is True, result


def test_stock_shortfall_prepares_the_verified_quantity_and_keeps_the_shortfall(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    _add_synthetic_sku(
        db_session, "p0:short", ingredient_ids='["chicken_wing"]', spec_quantity=500, spec_unit="g"
    )
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:short",
            price_fen=1980,
            available_qty=2,
            sellable=True,
        )
    )
    db_session.commit()

    requirement = _core_requirement("dish:dish-synthetic#chicken_wing", "chicken_wing")
    requirement["quantity"] = 500.0
    requirement["unit"] = "g"
    requirement["quantity_known"] = True
    result = validator.check_constraints(
        [
            {
                "sku_id": "p0:short",
                "quantity": 5,
                "role": "required",
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "catalog_spec",
            }
        ],
        ["p0:short"],
        coverage_intent="partial_ok",
        target_context={
            "group_id": "dish:dish-synthetic",
            "target_kind": "dish",
            "target_id": "dish-synthetic",
        },
    )
    row = result["items"][0]
    assert row["quantity"] == 2, row
    assert row["recommended_quantity"] == 5, row
    assert row["shortfall_quantity"] == 3, row
    assert row["availability"] == "insufficient_stock", row
    gap = result["gaps"][0]
    assert gap["kind"] == "insufficient_stock", gap
    # Amounts and packs are different dimensions and must never be mixed.
    assert gap["required_quantity"] == 500.0 and gap["unit"] == "g", gap
    assert gap["requested_pack_count"] == 5, gap
    assert gap["available_quantity"] == 2 and gap["shortfall_quantity"] == 3, gap
    assert gap["group_id"] == "dish:dish-synthetic", gap
    assert gap["target_kind"] == "dish" and gap["target_id"] == "dish-synthetic", gap
    assert "库存不足" in gap["message"], gap
    assert result["coverage_mode"] == "partial", result
    assert result["can_confirm"] is True, result


def test_cart_occupancy_tightens_the_prepared_quantity_but_not_the_demand(db_session):
    """D8/P0: the cart lowers what is prepared, never the requirement itself."""
    offer = (
        db_session.query(Offer)
        .filter_by(store_id="store-demo-01", sku_id="demo:tomato-fresh-500g")
        .one()
    )
    offer.available_qty = 5
    db_session.commit()
    service = ShoppingPlanService(db_session)
    new_plan = {
        "plan_id": "p0-cart",
        "plan_version": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "coverage_intent": "partial_ok",
        "gaps": [],
        "target": {"group_id": "dish:p0", "kind": "dish", "target_id": "p0", "name": "P0"},
        "items": [
            {
                "sku_id": "demo:tomato-fresh-500g",
                "quantity": 4,
                "recommended_quantity": 4,
                "quantity_source": "recommended",
                "role": "required",
                "selected": True,
                "group_id": "dish:p0",
                "availability": "available",
                "pack_source": "catalog_spec",
            }
        ],
    }
    merged = service.merge_plan(
        None,
        new_plan,
        group_id="dish:p0",
        operation="replace",
        cart_quantities={"demo:tomato-fresh-500g": 3},
    )
    row = merged["items"][0]
    assert row["quantity"] == 2, row
    assert row["recommended_quantity"] == 4, row
    assert row["shortfall_quantity"] == 2, row
    assert row["max_addable_quantity"] == 2, row
    assert merged["coverage_mode"] == "partial", merged
    assert merged["can_confirm"] is True, merged
    shortfall = [g for g in merged["gaps"] if g["kind"] == "insufficient_stock"]
    assert shortfall and shortfall[0]["shortfall_quantity"] == 2, merged["gaps"]


def test_scenario_with_a_missing_component_is_partial(monkeypatch, db_session):
    from app.services import shopping_plan_service as sps

    scenario = sps.get_scenario("hotpot")
    missing_component = scenario["components"][0]
    target_tags = {sps._normalize(tag) for tag in missing_component.get("any_tags") or []}
    real = sps.ShoppingPlanService._component_matches

    def patched(item, component_tags, component_ingredients, common_tags):
        if component_tags == target_tags:
            return False
        return real(item, component_tags, component_ingredients, common_tags)

    monkeypatch.setattr(sps.ShoppingPlanService, "_component_matches", staticmethod(patched))
    plan = sps.ShoppingPlanService(db_session).build_scenario_plan(
        "hotpot", people=4
    )
    assert plan["status"] == "ok", plan
    gap = next(
        g for g in plan["gaps"] if g.get("component_id") == missing_component["component_id"]
    )
    assert gap["kind"] == "not_found", gap
    assert gap["requiredness"] == "optional", gap
    assert plan["coverage_mode"] == "partial", plan
    # Optional rows stay freely selectable and the rest of the basket is real.
    assert any(row["selected"] for row in plan["items"]), plan["items"]
    assert plan["can_confirm"] is True, plan
    assert plan["missing_components"] == [
        {"component_id": missing_component["component_id"], "name": missing_component["name"]}
    ], plan["missing_components"]


def test_scenario_with_no_buyable_row_keeps_its_gaps(monkeypatch, db_session):
    from app.services import shopping_plan_service as sps

    monkeypatch.setattr(
        sps.ShoppingPlanService,
        "_component_matches",
        staticmethod(lambda item, component_tags, component_ingredients, common_tags: False),
    )
    result = sps.ShoppingPlanService(db_session).build_scenario_plan(
        "hotpot", people=4
    )
    assert result["status"] == "error", result
    assert result["code"] == "SUPPLY_UNAVAILABLE", result
    assert result["gaps"], result


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    """Nothing in this module may reach a real provider."""
    from app.llm import provider as llm_provider

    def _refuse(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("P0 partial-plan tests must not call a live model")

    monkeypatch.setattr(llm_provider, "get_semantic_provider", _refuse)

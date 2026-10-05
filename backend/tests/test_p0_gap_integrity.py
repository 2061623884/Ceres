"""P0 gap integrity: identity, resolution, dimensions, None-safety, authority.

These are the boundary regressions for the review findings on P0-a/b. Each one
fails against the previous implementation and pins the corrected rule:

* amounts (g/ml/pc) and packs are different dimensions and never mixed;
* an unknown pack size says what was really suggested (or that nothing was);
* a catalogue miss is a catalogue miss, not a claim about the whole store;
* a resolved row retires its carried gap; a fresh row fact replaces a stale one;
* two targets sharing one SKU keep both requirement identities;
* a stub/None supply attribute is ``unknown`` and never crashes or passes;
* ``full`` never authorizes confirming an incomplete plan, and a fully bought
  plan is never confirmable again.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.models.catalog import CatalogProduct
from app.models.store import Offer
from app.services import plan_contract as contract
from app.services.plan_revision_service import PlanRevisionService
from app.services.plan_validator import PlanValidator
from app.services.shopping_plan_service import ShoppingPlanService
from app.services.template_plan_service import TemplatePlanService
from support import post_turn


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


def _requirement(
    *,
    required_item_id: str,
    ingredient_id: str,
    name: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    role: str = "required",
) -> dict:
    return {
        "required_item_id": required_item_id,
        "name": name or ingredient_id,
        "ingredient_id": ingredient_id,
        "component_id": None,
        "quantity": quantity,
        "unit": unit,
        "quantity_known": quantity is not None,
        "requiredness": contract.requiredness_for_role(role),
        "source": {"kind": "local_recipe", "ref": required_item_id.split("#")[0]},
    }


# --------------------------------------------------------- amounts vs packs


def test_amount_and_pack_counts_are_never_mixed(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    db_session.add(
        CatalogProduct(
            sku_id="p0:pack-dim",
            name="鸡翅 500克",
            name_zh="鸡翅 500克",
            category_id="demo",
            review_status="approved",
            ingredient_ids='["chicken_wing"]',
            spec_quantity=500,
            spec_unit="g",
        )
    )
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:pack-dim",
            price_fen=1980,
            available_qty=2,
            sellable=True,
        )
    )
    db_session.commit()
    requirement = _requirement(
        required_item_id="dish:dish-dim#chicken_wing",
        ingredient_id="chicken_wing",
        name="鸡翅",
        quantity=900.0,
        unit="g",
    )
    result = validator.check_constraints(
        [
            {
                "sku_id": "p0:pack-dim",
                "quantity": 3,
                "role": "required",
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "catalog_spec",
            }
        ],
        ["p0:pack-dim"],
        coverage_intent="partial_ok",
        target_context={
            "group_id": "dish:dish-dim",
            "target_kind": "dish",
            "target_id": "dish-dim",
        },
    )
    gap = next(gap for gap in result["gaps"] if gap["kind"] == "insufficient_stock")
    assert gap["required_quantity"] == 900.0, gap
    assert gap["unit"] == "g", gap
    assert gap["requested_pack_count"] == 3, gap
    assert gap["available_quantity"] == 2, gap
    assert gap["shortfall_quantity"] == 1, gap
    assert "900" not in gap["message"], gap


def test_unknown_amount_does_not_invent_a_unit(db_session):
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")
    db_session.add(
        CatalogProduct(
            sku_id="p0:unknown-amount",
            name="生抽",
            name_zh="生抽",
            category_id="demo",
            review_status="approved",
            ingredient_ids='["soy_sauce"]',
        )
    )
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:unknown-amount",
            price_fen=320,
            available_qty=9,
            sellable=True,
        )
    )
    db_session.commit()
    requirement = _requirement(
        required_item_id="dish:dish-unk#soy_sauce", ingredient_id="soy_sauce", name="生抽"
    )
    result = validator.check_constraints(
        [
            {
                "sku_id": "p0:unknown-amount",
                "quantity": 1,
                "role": "required",
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "assumed_one",
            }
        ],
        ["p0:unknown-amount"],
        coverage_intent="partial_ok",
    )
    gap = next(gap for gap in result["gaps"] if gap["kind"] == "unknown")
    assert gap["required_quantity"] is None, gap
    assert gap["unit"] is None, gap
    assert gap["quantity_known"] is False, gap
    assert gap["requested_pack_count"] == 1, gap
    assert "1 件建议" in gap["message"], gap


def test_incompatible_units_say_no_pack_was_added(db_session):
    """No row at all: the wording must not claim a one-pack suggestion."""
    db_session.add(
        CatalogProduct(
            sku_id="p0:pc-only",
            name="按个卖的原料",
            name_zh="按个卖的原料",
            category_id="demo",
            review_status="approved",
            ingredient_ids='["p0_weird_ingredient"]',
            spec_quantity=1,
            spec_unit="pc",
        )
    )
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:pc-only",
            price_fen=500,
            available_qty=5,
            sellable=True,
        )
    )
    db_session.commit()
    dish = {
        "dish_id": "dish-p0-unit-mismatch",
        "name": "P0 单位不兼容",
        "base_people": 2,
        "required_items": [{"ingredient_id": "p0_weird_ingredient", "quantity_g": 400}],
        "optional_items": [],
        "pantry_items": [],
    }
    result = TemplatePlanService(db_session).validate_template_plan(dish, people=2)
    gap = next(gap for gap in result["gaps"] if gap["kind"] == "unknown")
    assert gap["unknown_of"] == "quantity", gap
    assert result["items"] == [], result
    assert "按最小包装" not in gap["message"], gap
    assert "无法换算" in gap["message"], gap
    assert result["coverage_mode"] == "uncovered", result
    assert result["can_confirm"] is False, result


def test_catalogue_miss_is_not_a_claim_about_the_store():
    core = contract.gap_message("not_found", name="罗勒", requiredness="core")
    optional = contract.gap_message("not_found", name="毛肚", requiredness="optional")
    for text in (core, optional):
        assert "没有找到" in text, text
        assert "本店没有" not in text, text
        assert "不卖" not in text, text


# ----------------------------------------------------- identity and resolution


def _basil_row(**overrides) -> dict:
    requirement = _requirement(
        required_item_id="dish:dish-x#basil",
        ingredient_id="basil",
        name="罗勒",
        quantity=20.0,
        unit="g",
    )
    row = {
        "sku_id": "demo:basil-100g",
        "quantity": 1,
        "recommended_quantity": 1,
        "role": "required",
        "selected": True,
        "group_id": "dish:dish-x",
        "target_kind": "dish",
        "target_id": "dish-x",
        "availability": "available",
        "pack_source": "catalog_spec",
        "shortfall_quantity": 0,
        "required_item_id": requirement["required_item_id"],
        "requirement": requirement,
    }
    row.update(overrides)
    return row


def test_a_resolved_row_retires_its_carried_gap():
    carried = [
        contract.make_gap(
            group_id="dish:dish-x",
            target_kind="dish",
            target_id="dish-x",
            kind="not_found",
            requiredness="core",
            key="basil",
            required_item_id="dish:dish-x#basil",
            ingredient_id="basil",
            name="罗勒",
            required_quantity=20.0,
            unit="g",
            quantity_known=True,
        )
    ]
    assert contract.collect_gaps(carried, [])[0]["gap_id"] == carried[0]["gap_id"]
    # The row now carries that requirement: the fresh (empty) row state wins.
    assert contract.collect_gaps(carried, [_basil_row()]) == []


def test_a_fresh_row_fact_replaces_a_stale_gap():
    stale = contract.make_gap(
        group_id="dish:dish-x",
        target_kind="dish",
        target_id="dish-x",
        kind="insufficient_stock",
        requiredness="core",
        required_item_id="dish:dish-x#basil",
        ingredient_id="basil",
        name="罗勒",
        available_quantity=1,
        shortfall_quantity=9,
    )
    row = _basil_row(
        availability="insufficient_stock",
        shortfall_quantity=2,
        max_addable_quantity=1,
    )
    gaps = contract.collect_gaps([stale], [row])
    assert len(gaps) == 1, gaps
    assert gaps[0]["shortfall_quantity"] == 2, gaps
    assert gaps[0]["gap_id"] == stale["gap_id"], gaps


def test_shared_sku_keeps_every_target_identity(db_session):
    service = ShoppingPlanService(db_session)
    db_session.add(
        CatalogProduct(
            sku_id="p0:shared",
            name="共用原料 500克",
            name_zh="共用原料 500克",
            category_id="demo",
            review_status="approved",
            ingredient_ids='["shared_thing"]',
            spec_quantity=500,
            spec_unit="g",
        )
    )
    db_session.add(
        Offer(
            store_id="store-demo-01",
            sku_id="p0:shared",
            price_fen=1000,
            available_qty=3,
            sellable=True,
        )
    )
    db_session.commit()

    def target(group_id: str, required_item_id: str) -> dict:
        requirement = _requirement(
            required_item_id=required_item_id,
            ingredient_id="shared_thing",
            name="共用原料",
            quantity=1000.0,
            unit="g",
        )
        return {
            "plan_id": "p0-shared",
            "plan_version": 1,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "coverage_intent": "partial_ok",
            "gaps": [],
            "target": {
                "group_id": group_id,
                "kind": "dish",
                "target_id": group_id.split(":", 1)[1],
                "name": group_id,
            },
            "items": [
                {
                    "sku_id": "p0:shared",
                    "quantity": 2,
                    "recommended_quantity": 2,
                    "quantity_source": "recommended",
                    "role": "required",
                    "selected": True,
                    "group_id": group_id,
                    "availability": "available",
                    "pack_source": "catalog_spec",
                    "required_item_id": requirement["required_item_id"],
                    "requirement": requirement,
                }
            ],
        }

    merged = service.merge_plan(None, target("dish:a", "dish:a#shared_thing"), group_id="dish:a", operation="replace")
    merged = service.merge_plan(
        merged,
        target("dish:b", "dish:b#shared_thing"),
        group_id="dish:b",
        operation="append",
    )
    row = merged["items"][0]
    assert len(row["contributions"]) == 2, row
    contribution_ids = {
        contribution["required_item_id"] for contribution in row["contributions"]
    }
    assert contribution_ids == {"dish:a#shared_thing", "dish:b#shared_thing"}, row
    assert all(
        contribution["requirement"]["source"]["kind"] == "local_recipe"
        for contribution in row["contributions"]
    ), row
    # 4 packs wanted, 3 in stock: one shortfall, reported once per target identity.
    assert row["quantity"] == 3 and row["recommended_quantity"] == 4, row
    gaps = {gap["required_item_id"]: gap for gap in merged["gaps"]}
    assert set(gaps) == {"dish:a#shared_thing", "dish:b#shared_thing"}, merged["gaps"]
    for gap in gaps.values():
        assert gap["kind"] == "insufficient_stock", gap
        assert gap["required_quantity"] == 1000.0 and gap["unit"] == "g", gap
        assert set(gap["required_item_ids"]) == {"dish:a#shared_thing", "dish:b#shared_thing"}
        assert "共用" in gap["message"], gap

    # Removing one target retires exactly that target's gap — and the remaining
    # target alone now fits in stock, so no gap is left at all.
    removed = service.merge_plan(
        merged, {"items": [], "target": {}}, group_id="dish:a", operation="remove"
    )
    assert removed["gaps"] == [], removed["gaps"]
    assert removed["coverage_mode"] == "full", removed
    assert {contribution["group_id"] for contribution in removed["items"][0]["contributions"]} == {
        "dish:b"
    }, removed["items"]


# --------------------------------------------------------------- None / stubs


def _stub_validator(db_session, offer) -> PlanValidator:
    validator = PlanValidator(db_session, "store-demo-01", "zone-default")

    class _StubOffers:
        def get_offer(self, sku_id):  # noqa: ANN001
            return offer

    validator.offers = _StubOffers()
    return validator


@pytest.mark.parametrize(
    "offer",
    [
        SimpleNamespace(sellable=True, available_qty=None, price_fen=100),
        SimpleNamespace(sellable=None, available_qty=5, price_fen=100),
        SimpleNamespace(sellable=True, available_qty=5, price_fen=None),
    ],
)
def test_an_unverified_supply_attribute_is_unknown_not_a_crash(db_session, offer):
    validator = _stub_validator(db_session, offer)
    db_session.add(
        CatalogProduct(
            sku_id="p0:stub",
            name="stub",
            name_zh="stub",
            category_id="demo",
            review_status="approved",
            ingredient_ids='["chicken_wing"]',
        )
    )
    db_session.commit()
    result = validator.check_constraints(
        [{"sku_id": "p0:stub", "quantity": 1, "role": "required"}],
        ["p0:stub"],
        coverage_intent="partial_ok",
    )
    assert result["validation_status"] == "passed", result
    gap = result["gaps"][0]
    assert gap["kind"] == "unknown", gap
    assert gap["unknown_of"] == "availability", gap
    assert gap["evidence"]["stock_verified"] is False, gap
    assert result["items"] == [], result
    assert result["can_confirm"] is False, result


# ------------------------------------------------------- intent / outstanding


def _selected_row(**overrides) -> dict:
    row = {
        "sku_id": "demo:x",
        "quantity": 1,
        "recommended_quantity": 1,
        "role": "required",
        "selected": True,
        "group_id": "dish:g",
        "target_kind": "dish",
        "target_id": "g",
        "availability": "available",
        "pack_source": "catalog_spec",
        "shortfall_quantity": 0,
        "max_addable_quantity": 9,
        "added_quantity": 0,
        "required_item_id": "dish:g#x",
        "requirement": _requirement(required_item_id="dish:g#x", ingredient_id="x"),
    }
    row.update(overrides)
    return row


def _core_gap() -> dict:
    return contract.make_gap(
        group_id="dish:g",
        target_kind="dish",
        target_id="g",
        kind="not_found",
        requiredness="core",
        required_item_id="dish:g#basil",
        ingredient_id="basil",
        name="罗勒",
    )


def test_full_intent_never_authorizes_an_incomplete_confirmation():
    row = _selected_row()
    gap = _core_gap()
    strict = contract.coverage([row], [gap], "full")
    assert strict["coverage_mode"] == "partial", strict
    assert strict["can_confirm"] is False, strict

    permissive = contract.coverage([row], [gap], "partial_ok")
    assert permissive["coverage_mode"] == "partial", permissive
    assert permissive["can_confirm"] is True, permissive


def test_a_fully_bought_plan_is_never_confirmable_again():
    bought = _selected_row(added_quantity=1)
    coverage = contract.coverage([bought], [], "partial_ok")
    assert coverage["coverage_mode"] == "full", coverage
    assert coverage["has_outstanding"] is False, coverage
    assert coverage["can_confirm"] is False, coverage
    # ... and the same rule holds for the row-add path's own recompute.
    pending = _selected_row()
    assert contract.coverage([pending], [], "partial_ok")["can_confirm"] is True


# ------------------------------------------------------- revision freshness


def test_revision_recomputes_shortfall_and_refreshes_the_quote(db_session):
    service = PlanRevisionService(db_session, "p0-owner", "store-demo-01", "zone-default")
    stale = _selected_row(
        sku_id="demo:tomato-fresh-500g",
        required_item_id="dish:g#tomato",
        requirement=_requirement(required_item_id="dish:g#tomato", ingredient_id="tomato"),
        recommended_quantity=2,
        quantity=1,
        availability="insufficient_stock",
        shortfall_quantity=1,
        max_addable_quantity=9,
        evidence={
            "sku_source": "store_offer",
            "quoted_at": "2020-01-01T00:00:00+00:00",
            "stock_verified": True,
            "unknown_constraints": [],
        },
    )
    # Raising the quantity back to what the requirement wanted clears the gap.
    raised = service._enrich_item(stale, True, 2, quantity_source="user")
    assert raised["shortfall_quantity"] == 0, raised
    assert raised["availability"] == "available", raised
    assert raised["recommended_quantity"] == 2, raised
    assert raised["evidence"]["quoted_at"] != "2020-01-01T00:00:00+00:00", raised
    assert contract.collect_gaps([], [raised]) == []

    # Lowering it below the wanted count keeps an honest requirement shortfall.
    lowered = service._enrich_item(stale, True, 1, quantity_source="user")
    assert lowered["shortfall_quantity"] == 1, lowered
    assert lowered["availability"] == "insufficient_stock", lowered
    gaps = contract.collect_gaps([], [lowered])
    assert gaps and gaps[0]["kind"] == "insufficient_stock", gaps
    assert gaps[0]["requested_pack_count"] == 2, gaps


# ------------------------------------------------------- empty group identity


def test_built_plan_gaps_always_carry_a_target_identity(client, semantic_provider):
    from support.semantic_agent import lookup_then_add_id

    target = lookup_then_add_id("dish", "三杯鸡", "dish-sanbei-ji", people=2)[0]

    def opt_in(request):
        question = next(q for q in request["pending_clarifications"] if q["slot"] == "supply_gap_choice")
        return {**target(request), "resolved_questions": [question["question_id"]]}

    semantic_provider([target, opt_in])
    sid = create_session(client)
    preview = turn(client, sid, "我想吃三杯鸡，2人").json()
    assert preview["plan"] is None, preview
    assert client.get("/api/v1/cart").json()["items"] == []
    body = turn(client, sid, "先为能买到的食材生成清单", preview).json()
    assert body["plan"] is not None, body
    assert body["plan"]["gaps"]
    for gap in body["plan"]["gaps"]:
        assert gap["group_id"], gap
        assert gap["target_kind"] == "dish", gap
        assert gap["target_id"], gap
    for row in body["plan"]["items"]:
        assert row["group_id"] == "dish:dish-sanbei-ji", row
        assert row["target_kind"] == "dish", row


def _rewrite_plan(client, task_id: str, mutate) -> dict:
    """Mutate a stored plan in place and return the new ``plan_json``."""
    from app.core import database as db_module
    from app.models.session import GuideTask

    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, task_id)
        plan = json.loads(task.plan_json)
        mutate(plan)
        task.plan_json = json.dumps(plan)
        db.commit()
        return plan
    finally:
        db.close()


def test_refresh_never_shrinks_a_hand_typed_quantity(client, semantic_provider):
    """A refresh re-checks facts; it does not silently overrule the shopper."""
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    plan = body["plan"]
    tomato = next(row for row in plan["items"] if "tomato" in row["sku_id"])

    from app.core import database as db_module
    from app.models.store import Offer

    db = db_module.SessionLocal()
    try:
        offer = (
            db.query(Offer)
            .filter_by(store_id="store-demo-01", sku_id=tomato["sku_id"])
            .one()
        )
        offer.available_qty = 2
        db.commit()
    finally:
        db.close()

    def mutate(stored: dict) -> None:
        for row in stored["items"]:
            if row["sku_id"] == tomato["sku_id"]:
                row["quantity"] = 5
                row["quantity_source"] = "user"
                row["user_quantity"] = 5
                row["max_addable_quantity"] = 5

    _rewrite_plan(client, body["task_id"], mutate)
    response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
        },
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    row = next(item for item in refreshed["items"] if item["sku_id"] == tomato["sku_id"])
    assert row["quantity"] == 5, row
    assert row["quantity_source"] == "user", row
    assert row["max_addable_quantity"] == 2, row
    assert any(item["sku_id"] == tomato["sku_id"] for item in refreshed["stale_items"]), refreshed
    assert refreshed["can_confirm"] is False, refreshed


def test_refresh_replaces_stale_supply_facts(client, semantic_provider):
    """A re-price uses freshly verified facts, never the old row's snapshot."""
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    plan = body["plan"]
    target = next(
        row
        for row in plan["items"]
        if row["availability"] == "available" and row["shortfall_quantity"] == 0
    )

    def mutate(stored: dict) -> None:
        for row in stored["items"]:
            if row["sku_id"] == target["sku_id"]:
                row["availability"] = "insufficient_stock"
                row["shortfall_quantity"] = 99
                evidence = dict(row.get("evidence") or {})
                evidence["quoted_at"] = "2020-01-01T00:00:00+00:00"
                row["evidence"] = evidence

    _rewrite_plan(client, body["task_id"], mutate)
    response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
        },
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    row = next(item for item in refreshed["items"] if item["sku_id"] == target["sku_id"])
    assert row["shortfall_quantity"] == 0, row
    assert row["availability"] == "available", row
    assert row["evidence"]["quoted_at"] != "2020-01-01T00:00:00+00:00", row
    assert row["evidence"]["sku_source"] == "store_offer", row
    assert row["required_item_id"] == target["required_item_id"], row


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    from app.llm import provider as llm_provider

    def _refuse(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("P0 gap-integrity tests must not call a live model")

    monkeypatch.setattr(llm_provider, "get_semantic_provider", _refuse)


# ------------------------------------------------- merge ledger / offer recheck


def _merge_service(offer):
    """``_collapse`` needs nothing but the offer lookup (no session, no catalog)."""
    service = ShoppingPlanService.__new__(ShoppingPlanService)
    service.offers = SimpleNamespace(get_offer=lambda sku_id: offer)
    return service


def _merge_row(**overrides) -> dict:
    row = {
        "sku_id": "p0:x",
        "quantity": 3,
        "recommended_quantity": 3,
        "selected": True,
        "role": "required",
        "group_id": "product:p0:x",
        "target_kind": "product",
        "target_id": "p0:x",
        "quantity_source": "recommended",
        "availability": "available",
        "pack_source": "catalog_spec",
        "shortfall_quantity": 0,
        "unit_price_fen": 100,
        "max_addable_quantity": 9,
    }
    row.update(overrides)
    return row


def _merge(service, row, *, cart_quantities=None):
    return service.merge_plan(
        None,
        {
            "plan_id": "plan-p0",
            "plan_version": 1,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "coverage_intent": "partial_ok",
            "gaps": [],
            "target": {"group_id": "product:p0:x", "kind": "product", "target_id": "p0:x", "name": "p0"},
            "items": [row],
        },
        group_id="product:p0:x",
        operation="replace",
        cart_quantities=cart_quantities,
    )


def test_merge_never_drops_below_the_added_ledger():
    """Repro: wanted 3, already added 2, offer 3, cart holds those 2."""
    service = _merge_service(SimpleNamespace(sellable=True, available_qty=3, price_fen=100))
    merged = _merge(
        service, _merge_row(added_quantity=2), cart_quantities={"p0:x": 2}
    )
    row = merged["items"][0]
    assert row["quantity"] == 3, row
    assert row["added_quantity"] == 2, row
    assert row["remaining_quantity"] == 1, row
    assert row["shortfall_quantity"] == 0, row
    assert row["max_addable_quantity"] == 1, row
    assert merged["can_confirm"] is True, merged


@pytest.mark.parametrize(
    ("offer", "expected_kind"),
    [
        (SimpleNamespace(sellable=False, available_qty=10, price_fen=100), "not_found"),
        (SimpleNamespace(sellable=True, available_qty=0, price_fen=100), "out_of_stock"),
        (SimpleNamespace(sellable=True, available_qty=None, price_fen=100), "unknown"),
        (SimpleNamespace(sellable=None, available_qty=10, price_fen=100), "unknown"),
        (SimpleNamespace(sellable=True, available_qty=10, price_fen=None), "unknown"),
        (None, "unknown"),
    ],
)
def test_merge_rechecks_the_live_offer_and_never_keeps_it_executable(offer, expected_kind):
    service = _merge_service(offer)
    merged = _merge(service, _merge_row())
    row = merged["items"][0]
    # The ticked row is kept (never silently deleted) but is not executable.
    assert row["availability"] == expected_kind, row
    assert row["max_addable_quantity"] == 0, row
    gap = merged["gaps"][0]
    assert gap["kind"] == expected_kind, gap
    assert gap["unknown_of"] == ("availability" if expected_kind == "unknown" else None), gap
    assert merged["coverage_mode"] == "uncovered", merged
    assert merged["can_confirm"] is False, merged


def test_merge_keeps_the_demand_gap_for_a_hand_typed_quantity():
    """Repro: the shopper lowered the row to 1 while the requirement wanted 3."""
    service = _merge_service(SimpleNamespace(sellable=True, available_qty=10, price_fen=100))
    merged = _merge(service, _merge_row(quantity=1, quantity_source="user"))
    row = merged["items"][0]
    assert row["quantity"] == 1, row
    assert row["recommended_quantity"] == 3, row
    assert row["shortfall_quantity"] == 2, row
    assert row["availability"] == "insufficient_stock", row
    assert merged["coverage_mode"] == "partial", merged
    gap = merged["gaps"][0]
    assert gap["kind"] == "insufficient_stock", gap
    assert gap["shortfall_quantity"] == 2 and gap["requested_pack_count"] == 3, gap


def test_the_content_signature_advances_on_executable_fact_changes():
    base = {"items": [_merge_row()], "targets": [], "coverage_mode": "full"}
    base_signature = ShoppingPlanService.content_signature(base)
    for changed in (
        {"unit_price_fen": 999},
        {"max_addable_quantity": 0},
        {"availability": "insufficient_stock"},
        {"shortfall_quantity": 1},
    ):
        altered = {**base, "items": [{**_merge_row(), **changed}]}
        assert ShoppingPlanService.content_signature(altered) != base_signature, changed

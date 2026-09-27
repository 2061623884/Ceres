"""Ensure dish template plans return raster product photos."""

from __future__ import annotations

import pytest

import json
import uuid
from pathlib import Path
from support import post_turn

ROOT = Path(__file__).resolve().parents[2]


def _session(client):
    return client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]


def _turn(client, session_id, message):
    return post_turn(client, session_id, message, None, request_id=str(uuid.uuid4()))


def test_qingjiao_rousi_plan_rows_use_demo_photo(client):
    sid = _session(client)
    turn = _turn(client, sid, "我想吃青椒肉丝")
    assert turn.status_code == 200
    plan = turn.json()["plan"]
    assert plan is not None
    for item in plan["items"]:
        assert item.get("image_kind") == "photo", (
            f"{item['sku_id']} image_kind={item.get('image_kind')} path={item.get('image_path')}"
        )
        assert str(item.get("image_path") or "").endswith((".jpg", ".jpeg", ".png", ".webp"))


# Dishes whose ingredients cannot all be resolved to demo SKUs yet — keyed by
# dish_id with the missing ingredient ids. Under the approved P0 contract these
# are no longer whole-plan failures: the resolvable rows are kept and every
# missing ingredient is reported as a structured gap (``coverage_mode=partial``,
# or ``uncovered`` when nothing at all can be bought).
EXPECTED_UNBUILDABLE: dict[str, str] = {
    "dish-sanbei-ji": "missing demo SKU for basil",
    "dish-shangtang-wawacai": "missing demo SKU for baby_cabbage, ham",
    "dish-donggua-paigu-tang": "missing demo SKU for winter_melon",
    "dish-ganjuo-huacai": "missing demo SKU for cauliflower",
    "dish-qingchao-kongxincai": "missing demo SKU for water_spinach",
    "dish-qingchao-douya": "missing demo SKU for bean_sprout",
    "dish-qingzhen-daiyu": "missing demo SKU for hairtail",
    "dish-qingzheng-luyu": "missing demo SKU for sea_bass",
    "dish-niurou-mian": "missing demo SKU for bok_choy",
    "dish-fanqie-dun-niunan": "missing demo SKU for beef_brisket",
    "dish-pidan-doufu": "missing demo SKU for preserved_egg",
    "dish-hongshao-daiyu": "missing demo SKU for hairtail",
    "dish-hongshao-niurou": "missing demo SKU for beef_brisket",
    "dish-luobo-paigu-tang": "missing demo SKU for radish",
    "dish-suanrong-fensi-baicai": "missing demo SKU for vermicelli",
    "dish-suanni-fensi-zhengxia": "missing demo SKU for vermicelli",
    "dish-doujiang-you-tiao": "missing demo SKU for youtiao",
    "dish-doupi-rousi": "missing demo SKU for tofu_skin",
    "dish-laziji": "missing demo SKU for dried_chili",
    "dish-suantang-feiniu": "missing demo SKU for enoki_mushroom",
    "dish-suancai-chaofen": "missing demo SKU for pickled_cabbage, vermicelli",
    "dish-suancai-yurou": "missing demo SKU for fish_fillet, pickled_cabbage",
    "dish-jiucai-chaodan": "missing demo SKU for chive",
    "dish-xianggu-qingcai": "missing demo SKU for bok_choy",
    "dish-mala-xia": "missing demo SKU for dried_chili",
}


def _missing_tokens(expected_reason: str) -> list[str]:
    if "for " not in expected_reason:
        return []
    tail = expected_reason.split("for ", 1)[1]
    return [t.strip() for part in tail.split(",") for t in part.split(" and ") if t.strip()]


def _gap_keys(result: dict) -> set[str]:
    return {
        str(gap.get(key))
        for gap in result.get("gaps") or []
        for key in ("ingredient_id", "sku_id", "component_id")
        if gap.get(key)
    }


def test_all_dish_templates_plan_with_raster_images(db_session):
    from app.services.template_plan_service import TemplatePlanService

    dishes = json.loads(
        (ROOT / "data" / "fixtures" / "chinese-dishes-v1.json").read_text(encoding="utf-8")
    )["dishes"]
    demo_fixture = {
        p["sku_id"]: p
        for p in json.loads(
            (ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8")
        )["products"]
    }
    placeholder_skus = {
        sku
        for sku, p in demo_fixture.items()
        if p.get("image_status") == "placeholder"
        or (p.get("metadata") or {}).get("image_status", {}).get("kind") == "placeholder"
    }
    service = TemplatePlanService(db_session)
    missing_by_dish: dict[str, list[str]] = {}
    source_gaps: dict[str, list[str]] = {}
    unexpected_failures: dict[str, list[str]] = {}
    reason_mismatches: dict[str, dict[str, str]] = {}
    coverage_drift: dict[str, dict[str, object]] = {}
    empty_gap_messages: list[str] = []
    assumed_pack_dishes: list[str] = []

    for dish in dishes:
        dish_id = dish["dish_id"]
        name = dish["name"]
        result = service.validate_template_plan(dish, people=2)
        if result.get("validation_status") != "passed":
            unexpected_failures[dish_id] = result.get("errors", [])
            continue

        items = result.get("items") or []
        gaps = result.get("gaps") or []
        selected = [item for item in items if item.get("selected")]
        unselected_required = [
            item
            for item in items
            if item.get("role") == "required" and not item.get("selected")
        ]
        # An optional row whose pack size is unknown is advisory: it is reported
        # as a gap but does not by itself downgrade requirement coverage.
        degrading = [
            gap
            for gap in gaps
            if not (
                gap.get("kind") == "unknown"
                and gap.get("unknown_of") == "quantity"
                and gap.get("requiredness") != "core"
            )
        ]
        expected_mode = "partial" if (degrading or unselected_required) else "full"
        if not selected and expected_mode == "partial":
            expected_mode = "uncovered"
        expected_confirm = bool(selected) and expected_mode != "uncovered"
        if (
            result.get("coverage_mode") != expected_mode
            or bool(result.get("can_confirm")) != expected_confirm
        ):
            coverage_drift[dish_id] = {
                "dish_name": name,
                "coverage_mode": result.get("coverage_mode"),
                "expected_mode": expected_mode,
                "can_confirm": result.get("can_confirm"),
                "expected_confirm": expected_confirm,
                "rows": len(items),
                "selected": len(selected),
                "gap_kinds": sorted(str(gap.get("kind")) for gap in gaps),
            }

        if dish_id in EXPECTED_UNBUILDABLE:
            expected = EXPECTED_UNBUILDABLE[dish_id]
            missing = [
                token for token in _missing_tokens(expected) if token not in _gap_keys(result)
            ]
            if missing:
                reason_mismatches[dish_id] = {
                    "dish_name": name,
                    "expected": expected,
                    "gaps": sorted(_gap_keys(result)),
                }

        if any(str(item.get("pack_source") or "") == "assumed_one" for item in items):
            assumed_pack_dishes.append(f"{dish_id}:{name}")
        for gap in gaps:
            if not str(gap.get("message") or "").strip():
                empty_gap_messages.append(f"{dish_id}:{gap.get('gap_id')}")

        bad = []
        source_bad = []
        for item in items:
            kind = item.get("image_kind")
            sku = item.get("sku_id", "")
            if kind == "placeholder" and sku in placeholder_skus:
                continue
            if kind != "photo":
                bad.append(f"{sku}:{kind}:{item.get('image_path')}")
            if not str(sku).startswith("demo:") and kind != "photo":
                ing = ",".join(item.get("ingredient_ids") or [])
                source_bad.append(f"{sku}({ing})")
        if bad:
            missing_by_dish[name] = bad
        if source_bad:
            source_gaps[name] = source_bad

    assert unexpected_failures == {}, f"new unregistered build failures: {unexpected_failures}"
    assert reason_mismatches == {}, f"registered gaps with wrong missing ingredient: {reason_mismatches}"
    assert coverage_drift == {}, f"coverage/can_confirm drift or unexplained gaps: {coverage_drift}"
    assert empty_gap_messages == [], f"gaps without user-readable wording: {empty_gap_messages}"
    assert missing_by_dish == {}, f"dishes with non-raster plan rows: {missing_by_dish}"
    assert source_gaps == {}, f"source-catalog raster gaps: {source_gaps}"
    print(
        f"dishes using the one-pack fallback (unknown quantity, never 'full'): "
        f"{len(assumed_pack_dishes)}"
    )


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

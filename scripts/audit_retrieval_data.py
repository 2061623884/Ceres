#!/usr/bin/env python3
"""Read-only retrieval data audit (S1). Outputs JSON report + summary table."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.services.ingredient_catalog import (
    all_ingredient_ids,
    load_ingredient_catalog,
)
from app.services.template_plan_service import UNIT_TO_GRAMS

FIXTURES = ROOT / "data" / "fixtures"
QUANTITY_KEYS = ("quantity_g", "quantity_pc", "quantity_ml")
VERIFIED_MAPPING_RELATIONS = frozenset({"declared", "reviewed"})

FORBIDDEN_SKU_INGREDIENT: set[tuple[str, str]] = {
    ("demo:shrimp-paste-200g", "shrimp"),
    ("demo:mushroom-white-200g", "shiitake"),
    ("demo:mushroom-white-200g", "wood_ear"),
    ("demo:mushroom-white-200g", "enoki_mushroom"),
    ("demo:pork-500g", "pork_ribs"),
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dish_ingredient_refs(dish: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for item in dish.get("required_items", []) + dish.get("optional_items", []):
        refs.append(("item", item.get("ingredient_id", "")))
    for entry in dish.get("pantry_items", []):
        if isinstance(entry, str):
            refs.append(("pantry", entry))
    return refs


def _sku_ingredient_refs(products: list[dict[str, Any]]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for product in products:
        sku = product.get("sku_id", "")
        for iid in product.get("ingredient_ids") or []:
            refs.append((sku, iid))
    return refs


def check_reference_legality(
    dishes: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    valid_ids = all_ingredient_ids()
    alias_map = load_ingredient_catalog()["alias_to_id"]
    invalid: list[dict[str, str]] = []
    for dish in dishes:
        for scope, iid in _dish_ingredient_refs(dish):
            if not iid:
                invalid.append({"dish_id": dish["dish_id"], "scope": scope, "ingredient_id": iid, "reason": "empty"})
            elif iid not in valid_ids and iid not in alias_map:
                invalid.append({"dish_id": dish["dish_id"], "scope": scope, "ingredient_id": iid, "reason": "unknown_id"})
    for sku_id, iid in _sku_ingredient_refs(products):
        if not iid:
            invalid.append({"sku_id": sku_id, "scope": "sku", "ingredient_id": iid, "reason": "empty"})
        elif iid not in valid_ids and iid not in alias_map:
            invalid.append({"sku_id": sku_id, "scope": "sku", "ingredient_id": iid, "reason": "unknown_id"})
    dish_refs = sum(len(_dish_ingredient_refs(d)) for d in dishes)
    sku_refs = len(_sku_ingredient_refs(products))
    return {
        "check": "reference_legality",
        "passed": len(invalid) == 0,
        "denominator": dish_refs + sku_refs,
        "failures": invalid,
    }


def check_retrievable_data(dishes: list[dict[str, Any]], legality: dict[str, Any]) -> dict[str, Any]:
    """Tier 1: legal ids + names; meta attributes not claimed."""
    dishes_with_meta = 0
    for dish in dishes:
        meta = dish.get("meta") or {}
        if any(meta.get(k) for k in ("description", "taste", "cooking_method", "difficulty", "cook_minutes")):
            dishes_with_meta += 1
        if meta.get("meal_types"):
            dishes_with_meta += 1
    return {
        "tier": "retrievable_data",
        "passed": legality.get("passed", False),
        "denominator_dishes": len(dishes),
        "dishes_with_nonempty_meta": dishes_with_meta,
        "note": "name/alias/ingredient retrieval only; attribute search data not populated",
    }


def check_alias_order_unique(dishes: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for dish in dishes:
        aliases = dish.get("aliases") or []
        seen: set[str] = set()
        for alias in aliases:
            if alias in seen:
                failures.append({"dish_id": dish["dish_id"], "alias": alias, "reason": "duplicate"})
            if alias == dish.get("name") or alias == dish.get("name_zh"):
                failures.append({"dish_id": dish["dish_id"], "alias": alias, "reason": "self_reference"})
            seen.add(alias)
    return {
        "check": "alias_order_unique",
        "passed": len(failures) == 0,
        "denominator": sum(len(d.get("aliases") or []) for d in dishes),
        "failures": failures,
    }


def check_wrong_equivalence(dishes: list[dict[str, Any]]) -> dict[str, Any]:
    known_distinct: dict[str, set[str]] = {"红烧肉": {"东坡肉"}}
    failures: list[dict[str, str]] = []
    for dish in dishes:
        name = dish.get("name") or dish.get("name_zh") or ""
        bad_aliases = known_distinct.get(name, set())
        for alias in dish.get("aliases") or []:
            if alias in bad_aliases:
                failures.append(
                    {
                        "dish_id": dish["dish_id"],
                        "dish_name": name,
                        "alias": alias,
                        "reason": "wrong_equivalence",
                    }
                )
    return {
        "check": "wrong_equivalence",
        "passed": len(failures) == 0,
        "denominator": sum(len(d.get("aliases") or []) for d in dishes),
        "failures": failures,
    }


def check_alias_collision(dishes: list[dict[str, Any]]) -> dict[str, Any]:
    alias_hits: dict[str, list[str]] = defaultdict(list)
    for dish in dishes:
        name = dish.get("name") or dish.get("name_zh") or ""
        for alias in dish.get("aliases") or []:
            alias_hits[alias].append(f"{dish['dish_id']}:{name}")
        alias_hits[name].append(f"{dish['dish_id']}:{name}")
    failures = [
        {"alias": alias, "dishes": hits, "reason": "collision"}
        for alias, hits in alias_hits.items()
        if len({h.split(":")[0] for h in hits}) > 1
    ]
    return {
        "check": "alias_collision",
        "passed": len(failures) == 0,
        "denominator": len(alias_hits),
        "failures": failures,
    }


def check_quantities(dishes: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for dish in dishes:
        for scope in ("required_items", "optional_items"):
            for item in dish.get(scope, []):
                dims = [k for k in QUANTITY_KEYS if k in item]
                if len(dims) != 1:
                    failures.append(
                        {
                            "dish_id": dish["dish_id"],
                            "ingredient_id": item.get("ingredient_id"),
                            "reason": "quantity_dimension_count",
                            "detail": dims,
                        }
                    )
                    continue
                val = item[dims[0]]
                if not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
                    failures.append(
                        {
                            "dish_id": dish["dish_id"],
                            "ingredient_id": item.get("ingredient_id"),
                            "reason": "non_positive_quantity",
                            "detail": val,
                        }
                    )
        pantry = dish.get("pantry_items") or []
        if not all(isinstance(p, str) for p in pantry):
            failures.append({"dish_id": dish["dish_id"], "reason": "pantry_not_string_array"})
    return {
        "check": "quantities_and_units",
        "passed": len(failures) == 0,
        "denominator": sum(
            len(d.get("required_items", [])) + len(d.get("optional_items", [])) for d in dishes
        ),
        "failures": failures,
    }


def check_sku_semantics(products: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for product in products:
        sku_id = product.get("sku_id", "")
        for iid in product.get("ingredient_ids") or []:
            if (sku_id, iid) in FORBIDDEN_SKU_INGREDIENT:
                failures.append(
                    {"sku_id": sku_id, "ingredient_id": iid, "reason": "cross_identity_mapping"}
                )
    return {
        "check": "sku_relation_semantics",
        "passed": len(failures) == 0,
        "denominator": len(products),
        "failures": failures,
    }


def _pack_qty_strict(sku: dict[str, Any], needed: dict[str, Any]) -> int | None:
    """Audit path: missing spec => None (no default 1 pack)."""
    spec_qty = sku.get("spec_quantity")
    spec_unit = sku.get("spec_unit")
    if spec_qty is None or not spec_unit:
        return None
    needed_g = needed.get("quantity_g")
    needed_pc = needed.get("quantity_pc")
    needed_ml = needed.get("quantity_ml")
    if spec_unit == "pc" and needed_pc:
        return max(1, math.ceil(float(needed_pc) / float(spec_qty)))
    if spec_unit in ("g", "kg") and needed_g:
        grams_per_unit = float(spec_qty) * UNIT_TO_GRAMS.get(spec_unit, 1.0)
        return max(1, math.ceil(float(needed_g) / grams_per_unit))
    if spec_unit in ("ml", "l") and needed_ml:
        ml_per_unit = float(spec_qty) * UNIT_TO_GRAMS.get(spec_unit, 1.0)
        return max(1, math.ceil(float(needed_ml) / ml_per_unit))
    return None


def _mapping_ok(sku: dict[str, Any], ingredient_id: str) -> bool:
    meta = sku.get("metadata") or {}
    mappings = meta.get("ingredient_mapping") or []
    for row in mappings:
        if row.get("ingredient_id") != ingredient_id:
            continue
        if row.get("relation") in VERIFIED_MAPPING_RELATIONS:
            return True
    # fixture-declared ingredient_ids without metadata wrapper
    if ingredient_id in (sku.get("ingredient_ids") or []):
        return sku.get("source") == "demo" or sku.get("sku_id", "").startswith("demo:")
    return False


def _sku_index(products: list[dict[str, Any]], offers: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_ing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product in products:
        offer = offers.get(product["sku_id"], {})
        row = {**product, **offer}
        if "sellable" not in row and product["sku_id"] in offers:
            row["sellable"] = True
        for iid in product.get("ingredient_ids") or []:
            by_ing[iid].append(row)
    return by_ing


def check_demo_required_fulfillable(
    dishes: list[dict[str, Any]],
    products: list[dict[str, Any]],
    offers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Demo-only required fulfillability (looser; for legacy check)."""
    offer_map = {o["sku_id"]: o for o in offers}
    by_ing = _sku_index(products, offer_map)
    unfulfilled: list[dict[str, Any]] = []
    fulfilled = 0
    for dish in dishes:
        base = dish.get("base_people") or 2
        scale = 2 / base
        missing: list[str] = []
        for item in dish.get("required_items", []):
            iid = item["ingredient_id"]
            needed = {
                "ingredient_id": iid,
                **{k: float(item[k]) * scale for k in QUANTITY_KEYS if k in item},
            }
            ok = False
            for sku in by_ing.get(iid, []):
                if not sku.get("sellable"):
                    continue
                if sku.get("review_status", "approved") != "approved":
                    continue
                packs = _pack_qty_strict(sku, needed)
                if packs is None:
                    continue
                if sku.get("available_qty", 0) < packs:
                    continue
                ok = True
                break
            if ok:
                fulfilled += 1
            else:
                missing.append(iid)
        if missing:
            unfulfilled.append(
                {
                    "dish_id": dish["dish_id"],
                    "dish_name": dish.get("name"),
                    "missing_required": missing,
                    "reason": "no_demo_sku_with_stock",
                }
            )
    total_refs = sum(len(d.get("required_items", [])) for d in dishes)
    return {
        "check": "demo_required_fulfillable",
        "passed": len(unfulfilled) == 0,
        "denominator_dishes": len(dishes),
        "denominator_required_refs": total_refs,
        "fulfilled_required_refs": fulfilled,
        "unfulfilled_dishes": unfulfilled,
    }


def check_verified_fulfillable_demo(
    dishes: list[dict[str, Any]],
    products: list[dict[str, Any]],
    offers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Tier 3: demo SKUs only, strict spec + declared/reviewed mapping."""
    offer_map = {o["sku_id"]: o for o in offers}
    demo_products = [p for p in products if str(p.get("sku_id", "")).startswith("demo:")]
    by_ing = _sku_index(demo_products, offer_map)
    unfulfilled: list[dict[str, Any]] = []
    verified_dishes = 0
    for dish in dishes:
        base = dish.get("base_people") or 2
        scale = 2 / base
        missing: list[str] = []
        for item in dish.get("required_items", []):
            iid = item["ingredient_id"]
            needed = {
                "ingredient_id": iid,
                **{k: float(item[k]) * scale for k in QUANTITY_KEYS if k in item},
            }
            ok = False
            for sku in by_ing.get(iid, []):
                if not sku.get("sellable") or sku.get("review_status", "approved") != "approved":
                    continue
                if not _mapping_ok(sku, iid):
                    continue
                packs = _pack_qty_strict(sku, needed)
                if packs is None:
                    continue
                if sku.get("available_qty", 0) < packs:
                    continue
                ok = True
                break
            if not ok:
                missing.append(iid)
        if missing:
            unfulfilled.append(
                {
                    "dish_id": dish["dish_id"],
                    "dish_name": dish.get("name"),
                    "missing_required": missing,
                }
            )
        else:
            verified_dishes += 1
    return {
        "tier": "verified_fulfillable_demo",
        "passed": len(unfulfilled) == 0,
        "denominator_dishes": len(dishes),
        "verified_dishes": verified_dishes,
        "unfulfilled_dishes": unfulfilled,
    }


def check_plan_generatable_runtime(dishes: list[dict[str, Any]], db_path: Path) -> dict[str, Any]:
    """Tier 2: runtime validator passed (includes inferred source + default pack qty)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.services.template_plan_service import TemplatePlanService

    if not db_path.is_file():
        return {
            "tier": "plan_generatable_runtime",
            "passed": False,
            "denominator_dishes": len(dishes),
            "generatable_dishes": 0,
            "note": f"candidate db missing: {db_path}",
        }
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        service = TemplatePlanService(db)
        generatable = 0
        failures: list[dict[str, Any]] = []
        for dish in dishes:
            result = service.validate_template_plan(dish, people=2)
            if result.get("validation_status") == "passed":
                generatable += 1
            else:
                failures.append(
                    {
                        "dish_id": dish["dish_id"],
                        "dish_name": dish.get("name"),
                        "errors": result.get("errors", []),
                    }
                )
        return {
            "tier": "plan_generatable_runtime",
            "passed": generatable == len(dishes),
            "denominator_dishes": len(dishes),
            "generatable_dishes": generatable,
            "failures": failures,
            "candidate_db": str(db_path),
        }
    finally:
        db.close()
        engine.dispose()


def _verify_image_file(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        return True
    except ImportError:
        return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    except Exception:
        return False


def check_images(products: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for product in products:
        meta = product.get("metadata") or {}
        if product.get("image_status") == "placeholder":
            status = {
                "kind": "placeholder",
                "file_verified": False,
                "semantic_match": "unknown",
                "source_url": None,
            }
        elif isinstance(meta.get("image_status"), dict):
            status = meta["image_status"]
        else:
            status = {
                "kind": "photo" if product.get("image_path") else "missing",
                "file_verified": None,
                "semantic_match": "unknown",
                "source_url": None,
            }
        file_verified = status.get("file_verified")
        path = product.get("image_path")
        if path and file_verified is None:
            img_path = ROOT / path
            file_verified = _verify_image_file(img_path) if img_path.exists() else False
        if status.get("kind") == "photo" and file_verified is not True:
            failures.append(
                {
                    "sku_id": product.get("sku_id", ""),
                    "reason": "photo_without_file_verified",
                    "image_path": path,
                }
            )
        rows.append(
            {
                "sku_id": product.get("sku_id"),
                "kind": status.get("kind"),
                "file_verified": file_verified,
                "semantic_match": status.get("semantic_match", "unknown"),
                "image_path": path,
            }
        )
    photo = sum(1 for r in rows if r["kind"] == "photo")
    placeholder = sum(1 for r in rows if r["kind"] == "placeholder")
    missing = sum(1 for r in rows if r["kind"] == "missing")
    file_ok = sum(1 for r in rows if r["file_verified"] is True)
    return {
        "tier": "image_coverage_demo",
        "check": "image_status",
        "passed": len(failures) == 0,
        "denominator": len(rows),
        "summary": {
            "photo": photo,
            "placeholder": placeholder,
            "missing": missing,
            "file_verified_true": file_ok,
            "semantic_match_unknown": sum(1 for r in rows if r["semantic_match"] == "unknown"),
        },
        "failures": failures,
        "items": rows,
    }


def build_report(label: str, candidate_db: Path | None) -> dict[str, Any]:
    dishes = _load_json(FIXTURES / "chinese-dishes-v1.json").get("dishes", [])
    demo = _load_json(FIXTURES / "demo-products.json").get("products", [])
    offers = _load_json(FIXTURES / "store-offers.json").get("offers", [])
    catalog = load_ingredient_catalog()
    legality = check_reference_legality(dishes, demo)
    checks = [
        legality,
        check_alias_order_unique(dishes),
        check_wrong_equivalence(dishes),
        check_alias_collision(dishes),
        check_quantities(dishes),
        check_sku_semantics(demo),
        check_demo_required_fulfillable(dishes, demo, offers),
        check_images(demo),
    ]
    tiers = [
        check_retrievable_data(dishes, legality),
        check_verified_fulfillable_demo(dishes, demo, offers),
        check_images(demo),
    ]
    if candidate_db:
        tiers.insert(1, check_plan_generatable_runtime(dishes, candidate_db))
    return {
        "label": label,
        "before_snapshot": "not_collected" if label == "after" else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_version": {
            "ingredient_catalog": catalog.get("version"),
            "chinese_dishes": _load_json(FIXTURES / "chinese-dishes-v1.json").get("version", "v1"),
            "demo_products": _load_json(FIXTURES / "demo-products.json").get("version", "v1"),
        },
        "counts": {
            "dishes": len(dishes),
            "demo_skus": len(demo),
            "demo_offers": len(offers),
            "canonical_ingredients": len(catalog["ingredients"]),
        },
        "coverage_tiers": tiers,
        "checks": checks,
        "summary": {
            "passed_checks": sum(1 for c in checks if c.get("passed")),
            "total_checks": len(checks),
        },
    }


def print_table(report: dict[str, Any]) -> None:
    print(f"=== Retrieval Data Audit ({report['label']}) ===")
    print(f"Dishes: {report['counts']['dishes']}  Demo SKUs: {report['counts']['demo_skus']}")
    print("Coverage tiers:")
    for tier in report.get("coverage_tiers", []):
        name = tier.get("tier") or tier.get("check")
        passed = tier.get("passed")
        if "generatable_dishes" in tier:
            print(f"  [{name}] generatable={tier['generatable_dishes']}/{tier['denominator_dishes']}")
        elif "verified_dishes" in tier:
            print(f"  [{name}] verified={tier['verified_dishes']}/{tier['denominator_dishes']}")
        elif "summary" in tier:
            s = tier["summary"]
            print(f"  [{name}] photo={s.get('photo')} placeholder={s.get('placeholder')} missing={s.get('missing')}")
        else:
            print(f"  [{name}] passed={passed}")
    for check in report["checks"]:
        status = "PASS" if check.get("passed") else "FAIL"
        name = check["check"]
        failures = check.get("failures") or check.get("unfulfilled_dishes") or []
        print(f"  [{status}] {name}  failures={len(failures)}")
    print(f"Summary: {report['summary']['passed_checks']}/{report['summary']['total_checks']} checks passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only retrieval data audit (S1)")
    parser.add_argument("--out", type=Path, help="Write JSON report to this path")
    parser.add_argument("--label", default="current", help="Report label (e.g. before / after)")
    parser.add_argument(
        "--candidate-db",
        type=Path,
        default=ROOT / "verification" / "data-completion" / "candidate_runtime.sqlite3",
        help="Runtime DB for plan_generatable tier",
    )
    args = parser.parse_args()

    candidate = args.candidate_db if args.candidate_db.exists() else None
    report = build_report(args.label, candidate)
    print_table(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote report to {args.out}")
    soft_fail = {"demo_required_fulfillable", "image_status"}
    if not all(c.get("passed") for c in report["checks"] if c["check"] not in soft_fail):
        sys.exit(1)


if __name__ == "__main__":
    main()

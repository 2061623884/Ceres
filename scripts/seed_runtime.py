#!/usr/bin/env python3
"""Idempotent runtime database seeding."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from scripts.import_db import INGREDIENT_CATALOG
from app.core.config import get_settings
from app.core.database import Base, create_db_engine, SessionLocal
from app.models.catalog import CatalogProduct, CatalogReview, PurchaseTemplate
from app.models.store import DeliveryQuote, Offer, Store

FIXTURES = ROOT / "data" / "fixtures"
KIND_TO_CATEGORY = {
    "vegetable": "vegetable",
    "meat": "meat",
    "seafood": "seafood",
    "fruit": "fruit",
    "condiment": "condiment",
}

INGREDIENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"tomato|番茄", re.I), "tomato"),
    (re.compile(r"lettuce|生菜", re.I), "lettuce"),
    (re.compile(r"spinach|菠菜", re.I), "spinach"),
    (re.compile(r"carrot|胡萝卜", re.I), "carrot"),
    (re.compile(r"onion|洋葱", re.I), "onion"),
    (re.compile(r"potato|土豆|马铃薯", re.I), "potato"),
    (re.compile(r"cabbage|卷心菜|包菜", re.I), "cabbage"),
    (re.compile(r"broccoli|西兰花", re.I), "broccoli"),
    (re.compile(r"cucumber|黄瓜", re.I), "cucumber"),
    (re.compile(r"mushroom|蘑菇", re.I), "mushroom"),
    (re.compile(r"garlic|大蒜|蒜", re.I), "garlic"),
    (re.compile(r"bell pepper|pepper|青椒|甜椒", re.I), "bell_pepper"),
    (re.compile(r"celery|芹菜", re.I), "celery"),
    (re.compile(r"eggplant|茄子", re.I), "eggplant"),
    (re.compile(r"chicken breast|鸡胸", re.I), "chicken_breast"),
    (re.compile(r"chicken thigh|鸡腿", re.I), "chicken_thigh"),
    (re.compile(r"ground beef|牛肉馅|牛绞", re.I), "ground_beef"),
    (re.compile(r"beef steak|牛排", re.I), "beef_steak"),
    (re.compile(r"pork|猪", re.I), "pork"),
    (re.compile(r"shrimp|prawn|虾", re.I), "shrimp"),
    (re.compile(r"salmon|三文鱼", re.I), "salmon"),
    (re.compile(r"cod|鳕鱼", re.I), "cod"),
    (re.compile(r"green bean|四季豆", re.I), "green_bean"),
    (re.compile(r"corn|玉米", re.I), "corn"),
    (re.compile(r"ginger|姜", re.I), "ginger"),
    (re.compile(r"tofu|豆腐", re.I), "tofu"),
    (re.compile(r"olive oil|橄榄油|huile d'olive|aceite de oliva", re.I), "olive_oil"),
    (re.compile(r"soy sauce|酱油|ketjap", re.I), "soy_sauce"),
    (re.compile(r"salt|盐|sel ", re.I), "salt"),
    (re.compile(r"vinegar|醋", re.I), "vinegar"),
    (re.compile(r"sugar|糖", re.I), "sugar"),
    (re.compile(r"butter|黄油", re.I), "butter"),
    (re.compile(r"apple|苹果", re.I), "apple"),
    (re.compile(r"banana|香蕉", re.I), "banana"),
    (re.compile(r"orange|橙", re.I), "orange"),
    (re.compile(r"lemon|柠檬", re.I), "lemon"),
]


def infer_ingredient_ids(name_en: str | None, name_zh: str | None, kind: str | None) -> list[str]:
    text = f"{name_en or ''} {name_zh or ''}"
    found: list[str] = []
    for pattern, ing_id in INGREDIENT_PATTERNS:
        if pattern.search(text):
            found.append(ing_id)
    if not found and kind == "condiment":
        if re.search(r"oil|油", text, re.I):
            found.append("olive_oil")
    return list(dict.fromkeys(found))

_NER_TERMS_SORTED: list[tuple[str, str, str]] = []
for _item in INGREDIENT_CATALOG:
    for _term in _item.ner_terms:
        _NER_TERMS_SORTED.append((_term.lower(), _item.name_norm, _item.kind))
_NER_TERMS_SORTED.sort(key=lambda x: -len(x[0]))


def match_source_product_ingredient(
    name_en: str | None, name_zh: str | None, kind: str
) -> str | None:
    """Map source product names/kind to INGREDIENT_CATALOG name_norm."""
    name_en_l = (name_en or "").lower()
    name_zh_s = (name_zh or "").strip()

    for item in INGREDIENT_CATALOG:
        if item.kind == kind and name_zh_s == item.name_zh:
            return item.name_norm

    zh_matches = [
        item
        for item in INGREDIENT_CATALOG
        if item.kind == kind and item.name_zh and item.name_zh in name_zh_s
    ]
    if zh_matches:
        return max(zh_matches, key=lambda i: len(i.name_zh)).name_norm

    for term, norm, item_kind in _NER_TERMS_SORTED:
        if item_kind == kind and term in name_en_l:
            return norm

    return None


def _backfill_ingredient_ids(product: CatalogProduct, ingredient_id: str) -> None:
    existing = json.loads(product.ingredient_ids or "[]")
    if not existing:
        product.ingredient_ids = json.dumps([ingredient_id])


def resolve_image_path(image_file: str | None) -> str | None:
    """Map source image_file to runtime image_path if the file exists."""
    if not image_file:
        return None
    filename = Path(image_file).name
    candidates = [
        ROOT / "data" / "images" / filename,
        ROOT / "data" / image_file.lstrip("/"),
    ]
    for img in candidates:
        if img.exists():
            rel = img.relative_to(ROOT)
            return str(rel).replace("\\", "/")
    return None


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalize_image_status(product: dict) -> dict:
    meta = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
    existing = meta.get("image_status")
    if isinstance(existing, dict):
        return existing
    raw = product.get("image_status")
    if raw == "placeholder":
        return {
            "kind": "placeholder",
            "file_verified": False,
            "semantic_match": "unknown",
            "source_url": None,
        }
    if product.get("image_path"):
        return {
            "kind": "photo",
            "file_verified": None,
            "semantic_match": "unknown",
            "source_url": None,
        }
    return {
        "kind": "missing",
        "file_verified": False,
        "semantic_match": "unknown",
        "source_url": None,
    }


def build_product_metadata(product: dict) -> dict:
    """Normalize SKU fixture metadata to DB schema."""
    if isinstance(product.get("metadata"), dict) and product["metadata"]:
        base = dict(product["metadata"])
    else:
        base = {}
    if not isinstance(base.get("image_status"), dict):
        base["image_status"] = _normalize_image_status(product)
    ingredient_ids = product.get("ingredient_ids") or []
    if "provenance" not in base:
        base["provenance"] = {
            "source": product.get("source", "demo"),
            "is_demo": product.get("source", "demo") == "demo",
            "source_barcode": product.get("source_barcode"),
        }
    if "ingredient_mapping" not in base:
        base["ingredient_mapping"] = [
            {
                "ingredient_id": iid,
                "relation": "declared",
                "evidence": "fixture:demo-products.json",
                "evidence_status": "demo_declared",
            }
            for iid in ingredient_ids
        ]
    if "allergens" not in base:
        base["allergens"] = {"status": "unknown", "values": [], "evidence": None}
    return base


def build_dish_metadata(dish: dict) -> dict:
    """Wrap dish fixture meta fields for DB storage."""
    if isinstance(dish.get("metadata"), dict) and dish["metadata"]:
        return dish["metadata"]
    return {
        "meta": dish.get("meta", {}),
        "meta_provenance": dish.get("meta_provenance", {}),
        "review": dish.get("review", {}),
    }


def build_source_product_metadata(
    *,
    barcode: str,
    ingredient_id: str | None,
    image_path: str | None,
) -> dict:
    mapping = []
    if ingredient_id:
        mapping.append(
            {
                "ingredient_id": ingredient_id,
                "relation": "inferred",
                "evidence": f"source_db:{barcode}",
                "evidence_status": "pending",
            }
        )
    kind = "photo" if image_path else "missing"
    return {
        "image_status": {
            "kind": kind,
            "file_verified": None,
            "semantic_match": "unknown",
            "source_url": None,
        },
        "provenance": {
            "source": "source_db",
            "is_demo": False,
            "source_barcode": barcode,
        },
        "ingredient_mapping": mapping,
        "allergens": {"status": "unknown", "values": [], "evidence": None},
    }


def deterministic_price_fen(sku_id: str) -> int:
    """Stable default offer price (no hash())."""
    data = load_json("default-offer-prices.json")
    overrides = data.get("sku_prices", {})
    if sku_id in overrides:
        return int(overrides[sku_id])
    base = int(data.get("default_price_fen", 1500))
    return base + (sum(ord(c) for c in sku_id) % 2000)


def seed_from_source(db: Session, settings) -> int:
    """Import non-quarantined source products as approved, sellable catalog SKUs."""
    source_path = settings.source_db_path
    if not source_path.exists():
        return 0
    review_data = load_json("catalog-review.json")
    quarantined = {
        item["source_barcode"]
        for item in review_data.get("items", [])
        if item.get("status") == "quarantined"
    }
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT barcode, name_en, name_zh, kind, brands, image_file FROM products"
    )
    count = 0
    for row in cur:
        barcode = row["barcode"]
        if barcode in quarantined:
            continue
        sku_id = barcode
        existing = db.get(CatalogProduct, sku_id)
        image_path = resolve_image_path(row["image_file"])
        ingredient_id = match_source_product_ingredient(
            row["name_en"], row["name_zh"], row["kind"]
        )
        metadata = build_source_product_metadata(
            barcode=barcode,
            ingredient_id=ingredient_id,
            image_path=image_path,
        )
        if existing:
            if image_path and not existing.image_path:
                existing.image_path = image_path
            if ingredient_id:
                _backfill_ingredient_ids(existing, ingredient_id)
            if existing.review_status == "unreviewed":
                existing.review_status = "approved"
            if not existing.metadata_json or existing.metadata_json == "{}":
                existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
            count += 1
            continue
        category_id = KIND_TO_CATEGORY.get(row["kind"], row["kind"])
        db.add(
            CatalogProduct(
                sku_id=sku_id,
                source_barcode=barcode,
                name=row["name_en"] or row["name_zh"],
                name_zh=row["name_zh"],
                category_id=category_id,
                ingredient_ids=json.dumps([ingredient_id]) if ingredient_id else "[]",
                brand=row["brands"],
                image_path=image_path,
                source="source_db",
                review_status="approved",
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        )
        count += 1
    conn.close()
    return count


def seed_reviews(db: Session) -> None:
    data = load_json("catalog-review.json")
    for item in data.get("items", []):
        barcode = item["source_barcode"]
        existing = db.get(CatalogReview, barcode)
        if existing:
            existing.status = item["status"]
            existing.corrected_category = item.get("corrected_category")
            existing.reason = item.get("reason")
            existing.evidence = item.get("evidence")
            existing.review_version = data.get("review_version", "v1")
        else:
            db.add(
                CatalogReview(
                    source_barcode=barcode,
                    status=item["status"],
                    corrected_category=item.get("corrected_category"),
                    ingredient_ids=json.dumps(item.get("ingredient_ids", [])),
                    reason=item.get("reason"),
                    evidence=item.get("evidence"),
                    review_version=data.get("review_version", "v1"),
                )
            )


def validate_sellable_demo_rasters() -> list[str]:
    """Every demo SKU must either have an on-disk raster photo or be an explicitly
    declared honest placeholder.

    A product that declares ``"image_status": "placeholder"`` must *not* point at
    an image file: reusing an unrelated product photo would be worse than a
    visible placeholder. The check covers every demo product, not only the ones
    listed in ``store-offers.json``.
    """
    from app.services.image_assets import is_raster_image_path

    errors: list[str] = []
    for product in load_json("demo-products.json").get("products", []):
        sku_id = product.get("sku_id")
        if not sku_id:
            errors.append("demo product without sku_id")
            continue
        image_path = product.get("image_path")
        if product.get("image_status") == "placeholder":
            if image_path:
                errors.append(
                    f"{sku_id}: declared placeholder must not ship an image_path ({image_path})"
                )
            continue
        if not is_raster_image_path(image_path, ROOT):
            errors.append(f"{sku_id}: invalid demo image_path ({image_path or 'missing'})")
    return errors


def validate_scenario_fixture() -> list[str]:
    """The scenario fixture is reviewable data: validate it before it is used."""
    errors: list[str] = []
    products = {
        p["sku_id"]: p for p in load_json("demo-products.json").get("products", [])
    }
    approved_tags: set[str] = set()
    approved_ingredients: set[str] = set()
    for p in products.values():
        approved_tags.update(p.get("usage_tags", []))
        approved_ingredients.update(p.get("ingredient_ids", []))
    for scenario in load_json("shopping-scenarios.json").get("scenarios", []):
        scenario_id = scenario.get("scenario_id")
        if not scenario_id:
            errors.append("scenario without scenario_id")
        if not scenario.get("components"):
            errors.append(f"{scenario_id}: no components")
        if not scenario.get("common_tags"):
            errors.append(f"{scenario_id}: no common_tags")
        seen_components: set[str] = set()
        for component in scenario.get("components", []):
            component_id = component.get("component_id")
            if not component_id or component_id in seen_components:
                errors.append(f"{scenario_id}: missing/duplicate component_id {component_id!r}")
                continue
            seen_components.add(component_id)
            tags = set(component.get("any_tags") or [])
            ingredients = set(component.get("ingredient_ids") or [])
            if not tags and not ingredients:
                errors.append(f"{scenario_id}/{component_id}: no recall key")
            if tags and not tags & approved_tags:
                errors.append(f"{scenario_id}/{component_id}: no product carries {sorted(tags)}")
            if ingredients and not ingredients & approved_ingredients:
                errors.append(
                    f"{scenario_id}/{component_id}: no product carries {sorted(ingredients)}"
                )
    return errors



def seed_demo_products(db: Session) -> int:
    raster_errors = validate_sellable_demo_rasters()
    if raster_errors:
        raise ValueError(
            "Sellable demo products missing raster images:\n" + "\n".join(raster_errors)
        )
    data = load_json("demo-products.json")
    count = 0
    for p in data.get("products", []):
        existing = db.get(CatalogProduct, p["sku_id"])
        metadata = build_product_metadata(p)
        if existing:
            if p.get("category_id"):
                existing.category_id = p["category_id"]
            if p.get("name"):
                existing.name = p["name"]
            if p.get("name_zh") is not None:
                existing.name_zh = p["name_zh"]
            if p.get("brand") is not None:
                existing.brand = p["brand"]
            if p.get("review_status"):
                existing.review_status = p["review_status"]
            # Fixture data is authoritative for demo SKUs: a re-seed must restore
            # the reviewable tags/spec instead of keeping stale ones.
            existing.usage_tags = json.dumps(p.get("usage_tags", []))
            if p.get("image_path"):
                existing.image_path = p["image_path"]
            elif p.get("image_status") == "placeholder":
                existing.image_path = None
            if p.get("ingredient_ids"):
                existing.ingredient_ids = json.dumps(p["ingredient_ids"])
            if p.get("spec_quantity") is not None:
                existing.spec_quantity = p["spec_quantity"]
            if p.get("spec_unit"):
                existing.spec_unit = p["spec_unit"]
            if p.get("product_type"):
                existing.product_type = p["product_type"]
            existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
            count += 1
            continue
        db.add(
            CatalogProduct(
                sku_id=p["sku_id"],
                source_barcode=None,
                name=p["name"],
                name_zh=p.get("name_zh"),
                category_id=p["category_id"],
                ingredient_ids=json.dumps(p.get("ingredient_ids", [])),
                brand=p.get("brand"),
                image_path=p.get("image_path"),
                source=p.get("source", "demo"),
                review_status=p.get("review_status", "approved"),
                spec_quantity=p.get("spec_quantity"),
                spec_unit=p.get("spec_unit"),
                usage_tags=json.dumps(p.get("usage_tags", [])),
                product_type=p.get("product_type"),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        )
        count += 1
    return count


def ensure_catalog_schema(engine) -> None:
    inspector = inspect(engine)
    if "catalog_products" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("catalog_products")}
    if "product_type" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE catalog_products ADD COLUMN product_type VARCHAR(32)")
            )


def seed_store_offers(db: Session) -> None:
    data = load_json("store-offers.json")
    store_data = data["store"]
    if not db.get(Store, store_data["store_id"]):
        db.add(
            Store(
                store_id=store_data["store_id"],
                name=store_data["name"],
                is_demo=store_data.get("is_demo", True),
                delivery_zone_id=store_data.get("delivery_zone_id", "zone-default"),
            )
        )
    delivery = data.get("delivery", {})
    existing_quote = (
        db.query(DeliveryQuote)
        .filter_by(store_id=store_data["store_id"], zone_id=delivery.get("zone_id", "zone-default"))
        .first()
    )
    if not existing_quote:
        db.add(
            DeliveryQuote(
                store_id=store_data["store_id"],
                zone_id=delivery.get("zone_id", "zone-default"),
                reachable=delivery.get("reachable", True),
                eta_minutes=delivery.get("eta_minutes", 45),
            )
        )
    for offer in data.get("offers", []):
        existing = (
            db.query(Offer)
            .filter_by(store_id=store_data["store_id"], sku_id=offer["sku_id"])
            .first()
        )
        if existing:
            continue
        else:
            db.add(
                Offer(
                    store_id=store_data["store_id"],
                    sku_id=offer["sku_id"],
                    price_fen=offer["price_fen"],
                    available_qty=offer.get("available_qty", 99),
                    sellable=True,
                    is_demo=True,
                )
            )
    # Price approved source products with default demo prices. The flush matters:
    # a session with autoflush disabled would otherwise not see the demo products
    # inserted earlier in the same transaction, and they would end up with no
    # offer at all — present in the catalog but unsellable.
    db.flush()
    products = db.query(CatalogProduct).filter_by(review_status="approved").all()
    for p in products:
        existing = (
            db.query(Offer)
            .filter_by(store_id=store_data["store_id"], sku_id=p.sku_id)
            .first()
        )
        if not existing:
            price_data = load_json("default-offer-prices.json")
            db.add(
                Offer(
                    store_id=store_data["store_id"],
                    sku_id=p.sku_id,
                    price_fen=deterministic_price_fen(p.sku_id),
                    available_qty=int(price_data.get("default_available_qty", 20)),
                    sellable=True,
                    is_demo=True,
                )
            )


def ensure_purchase_template_schema(engine) -> None:
    """Add aliases_json column to existing SQLite DBs (create_all does not alter)."""
    inspector = inspect(engine)
    if "purchase_templates" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("purchase_templates")}
    if "aliases_json" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE purchase_templates ADD COLUMN aliases_json TEXT DEFAULT '[]'")
        )


def ensure_metadata_schema(engine) -> None:
    """Add metadata_json columns to catalog tables when missing."""
    inspector = inspect(engine)
    migrations = [
        ("purchase_templates", "metadata_json", "'{}'"),
        ("catalog_products", "metadata_json", "'{}'"),
    ]
    for table, column, default in migrations:
        if table not in inspector.get_table_names():
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column in columns:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} TEXT DEFAULT {default}")
            )


def _upsert_purchase_template(db: Session, payload: dict, source: str = "fixture") -> None:
    template_id = payload["template_id"]
    aliases = payload.get("aliases", [])
    metadata = payload.get("metadata") or build_dish_metadata(payload)
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    existing = db.get(PurchaseTemplate, template_id)
    if existing:
        existing.scenario = payload["scenario"]
        existing.aliases_json = json.dumps(aliases, ensure_ascii=False)
        existing.base_people = payload.get("base_people", 2)
        existing.required_items = json.dumps(payload["required_items"], ensure_ascii=False)
        existing.optional_items = json.dumps(payload.get("optional_items", []), ensure_ascii=False)
        existing.pantry_items = json.dumps(payload.get("pantry_items", []), ensure_ascii=False)
        existing.metadata_json = metadata_json
        existing.source = source
    else:
        db.add(
            PurchaseTemplate(
                template_id=template_id,
                scenario=payload["scenario"],
                aliases_json=json.dumps(aliases, ensure_ascii=False),
                base_people=payload.get("base_people", 2),
                required_items=json.dumps(payload["required_items"], ensure_ascii=False),
                optional_items=json.dumps(payload.get("optional_items", []), ensure_ascii=False),
                pantry_items=json.dumps(payload.get("pantry_items", []), ensure_ascii=False),
                metadata_json=metadata_json,
                source=source,
            )
        )


def seed_templates(db: Session) -> None:
    data = load_json("purchase-templates.json")
    for t in data.get("templates", []):
        _upsert_purchase_template(db, t, source="fixture")


def seed_chinese_dish_templates(db: Session) -> int:
    data = load_json("chinese-dishes-v1.json")
    count = 0
    for dish in data.get("dishes", []):
        payload = {
            "template_id": dish["dish_id"],
            "scenario": dish.get("name") or dish.get("name_zh", ""),
            "aliases": dish.get("aliases", []),
            "base_people": dish.get("base_people", 2),
            "required_items": dish.get("required_items", []),
            "optional_items": dish.get("optional_items", []),
            "pantry_items": dish.get("pantry_items", []),
            "metadata": build_dish_metadata(dish),
        }
        _upsert_purchase_template(db, payload, source="chinese-dishes-v1")
        count += 1
    return count


def main(fixture_only: bool = False) -> None:
    settings = get_settings()
    scenario_errors = validate_scenario_fixture()
    if scenario_errors:
        raise ValueError("Invalid shopping scenario fixture:\n" + "\n".join(scenario_errors))
    engine = create_db_engine()
    Base.metadata.create_all(bind=engine)
    ensure_purchase_template_schema(engine)
    ensure_metadata_schema(engine)
    ensure_catalog_schema(engine)
    from app.core.database import ensure_runtime_schema

    ensure_runtime_schema(engine)
    db = SessionLocal()
    try:
        source_count = 0
        if not fixture_only:
            source_count = seed_from_source(db, settings)
        demo_count = seed_demo_products(db)
        seed_reviews(db)
        seed_store_offers(db)
        seed_templates(db)
        dish_count = seed_chinese_dish_templates(db)
        db.commit()
        total = db.query(CatalogProduct).filter_by(review_status="approved").count()
        print(
            f"Seed complete: source={source_count}, demo={demo_count}, "
            f"dishes={dish_count}, approved_total={total}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the Ceres runtime database.")
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Skip importing products from the external source database.",
    )
    main(fixture_only=parser.parse_args().fixture_only)

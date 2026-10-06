"""S1 data completion regression tests."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]


def _load_dishes() -> list[dict]:
    return json.loads(
        (ROOT / "data" / "fixtures" / "chinese-dishes-v1.json").read_text(encoding="utf-8")
    )["dishes"]


def _dish_refs(dish: dict) -> list[str]:
    refs: list[str] = []
    for item in dish.get("required_items", []) + dish.get("optional_items", []):
        refs.append(item["ingredient_id"])
    for entry in dish.get("pantry_items", []):
        refs.append(entry if isinstance(entry, str) else entry["ingredient_id"])
    return refs


def test_fixture_files_use_utf8_encoding():
    paths = [
        ROOT / "data" / "fixtures" / "ingredient-catalog.json",
        ROOT / "data" / "fixtures" / "chinese-dishes-v1.json",
        ROOT / "data" / "fixtures" / "demo-products.json",
        ROOT / "scripts" / "audit_catalog.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert text, f"{path} should be readable as UTF-8"


def test_dish_ingredient_ids_are_legal():
    from app.services.ingredient_catalog import is_valid_ingredient_id

    invalid: list[tuple[str, str]] = []
    for dish in _load_dishes():
        for iid in _dish_refs(dish):
            if not is_valid_ingredient_id(iid):
                invalid.append((dish["dish_id"], iid))
    assert invalid == [], f"illegal ingredient ids: {invalid}"


def test_demo_sku_ingredient_ids_are_legal():
    from app.services.ingredient_catalog import is_valid_ingredient_id

    demo = json.loads(
        (ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8")
    )["products"]
    invalid: list[tuple[str, str]] = []
    for product in demo:
        for iid in product.get("ingredient_ids") or []:
            if not is_valid_ingredient_id(iid):
                invalid.append((product["sku_id"], iid))
    assert invalid == [], f"illegal demo sku ingredient ids: {invalid}"


def test_cola_chicken_wing_plan_includes_cola(db_session):
    from app.models.catalog import CatalogProduct
    from app.services.template_plan_service import TemplatePlanService

    dish = next(d for d in _load_dishes() if d["dish_id"] == "dish-kele-jichi")
    cola_item = next(i for i in dish["required_items"] if i["ingredient_id"] == "cola")
    assert cola_item.get("quantity_ml") == 330
    assert "cola" not in dish.get("pantry_items", [])

    service = TemplatePlanService(db_session)
    result = service.validate_template_plan(dish, people=2)
    assert result["validation_status"] == "passed"
    skus = {item["sku_id"] for item in result["items"]}
    cola_rows = [item for item in result["items"] if item["requirement"]["ingredient_id"] == "cola"]
    assert len(cola_rows) == 1, result
    cola = cola_rows[0]
    assert cola["role"] == "required" and cola["quantity"] >= 1, cola
    assert cola["requirement"]["quantity"] == 330 and cola["requirement"]["unit"] == "ml", cola
    assert "cola" in json.loads(db_session.get(CatalogProduct, cola["sku_id"]).ingredient_ids)
    assert "demo:chicken-wing-500g" in skus


def test_seed_updates_stale_demo_name(db_session):
    from app.models.catalog import CatalogProduct
    from scripts.seed_runtime import seed_demo_products

    row = db_session.get(CatalogProduct, "demo:pork-500g")
    assert row is not None
    row.name = "Pork Loin 500g"
    row.name_zh = "猪里脊 500克"
    row.brand = "旧品牌"
    db_session.commit()

    seed_demo_products(db_session)
    db_session.commit()

    row = db_session.get(CatalogProduct, "demo:pork-500g")
    assert row.name_zh == "猪肩肉 500克"
    assert row.brand == "演示品牌"


def test_demo_skus_no_category_mixing():
    demo = json.loads(
        (ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8")
    )["products"]
    forbidden = {
        ("demo:shrimp-paste-200g", "shrimp"),
        ("demo:mushroom-white-200g", "shiitake"),
        ("demo:mushroom-white-200g", "wood_ear"),
        ("demo:mushroom-white-200g", "enoki_mushroom"),
        ("demo:pork-500g", "pork_ribs"),
    }
    violations = []
    for product in demo:
        sku = product["sku_id"]
        ids = set(product.get("ingredient_ids") or [])
        for rule_sku, bad_id in forbidden:
            if sku == rule_sku and bad_id in ids:
                violations.append((sku, bad_id))
    assert violations == []


def test_metadata_roundtrip_dish_and_product(db_session):
    from app.models.catalog import CatalogProduct, PurchaseTemplate
    from app.services.catalog_service import product_to_dict
    from app.services.template_matcher import dish_fixture_to_dict, template_record_to_dict

    dish = _load_dishes()[0]
    fixture_meta = dish_fixture_to_dict(dish)["metadata"]
    row = db_session.get(PurchaseTemplate, dish["dish_id"])
    assert row is not None
    db_meta = template_record_to_dict(row)["metadata"]
    assert db_meta == fixture_meta

    demo = json.loads(
        (ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8")
    )["products"][0]
    product = db_session.get(CatalogProduct, demo["sku_id"])
    assert product is not None
    api_meta = product_to_dict(product)["metadata"]
    assert "image_status" in api_meta
    assert "provenance" in api_meta


def test_double_seed_idempotent_on_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "seed-idempotent.sqlite3"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SOURCE_DATABASE_PATH", str(ROOT / "data" / "sale_guide.db"))

    from app.core.config import get_settings
    from app.core.database import Base
    from app.models import cart, catalog, conversation, session as session_models, store, trace  # noqa: F401
    from scripts.seed_runtime import (
        ensure_catalog_schema,
        ensure_metadata_schema,
        ensure_purchase_template_schema,
        seed_chinese_dish_templates,
        seed_demo_products,
        seed_from_source,
        seed_reviews,
        seed_store_offers,
        seed_templates,
    )

    get_settings.cache_clear()
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    ensure_purchase_template_schema(engine)
    ensure_metadata_schema(engine)
    ensure_catalog_schema(engine)
    Session = sessionmaker(bind=engine)

    def snapshot() -> dict:
        db = Session()
        try:
            from app.models.catalog import CatalogProduct, PurchaseTemplate
            from app.models.store import Offer

            products = sorted(
                (
                    p.sku_id,
                    p.name,
                    p.ingredient_ids,
                    p.metadata_json,
                    p.spec_quantity,
                    p.spec_unit,
                )
                for p in db.query(CatalogProduct).all()
            )
            templates = sorted(
                (
                    t.template_id,
                    t.required_items,
                    t.metadata_json,
                )
                for t in db.query(PurchaseTemplate).all()
            )
            offers = sorted(
                (o.sku_id, o.price_fen, o.available_qty, o.sellable)
                for o in db.query(Offer).all()
            )
            return {"products": products, "templates": templates, "offers": offers}
        finally:
            db.close()

    def run_seed() -> None:
        db = Session()
        try:
            seed_from_source(db, settings)
            seed_demo_products(db)
            seed_reviews(db)
            seed_store_offers(db)
            seed_templates(db)
            seed_chinese_dish_templates(db)
            db.commit()
        finally:
            db.close()

    settings = get_settings()
    run_seed()
    first = snapshot()
    run_seed()
    second = snapshot()
    assert first == second

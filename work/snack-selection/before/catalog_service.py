"""Catalog search and retrieval."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.catalog import CatalogProduct, CatalogReview
from app.models.store import Offer


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def product_to_dict(p: CatalogProduct, offer: Offer | None = None) -> dict[str, Any]:
    return {
        "sku_id": p.sku_id,
        "name": p.name,
        "name_zh": p.name_zh,
        "category_id": p.category_id,
        "brand": p.brand,
        "image_path": p.image_path,
        "source": p.source,
        "review_status": p.review_status,
        "spec_quantity": p.spec_quantity,
        "spec_unit": p.spec_unit,
        "usage_tags": _parse_json_list(p.usage_tags),
        "ingredient_ids": _parse_json_list(p.ingredient_ids),
        "product_type": p.product_type,
        "metadata": _parse_metadata(p.metadata_json),
        "price_fen": offer.price_fen if offer else None,
        "available_qty": offer.available_qty if offer else None,
        "sellable": offer.sellable if offer else False,
    }


class CatalogService:
    def __init__(self, db: Session, store_id: str = "store-demo-01"):
        self.db = db
        self.store_id = store_id

    def _quarantined_barcodes(self) -> set[str]:
        rows = self.db.query(CatalogReview).filter_by(status="quarantined").all()
        return {row.source_barcode for row in rows}

    def get_categories(self) -> list[dict[str, Any]]:
        rows = (
            self.db.query(CatalogProduct.category_id, CatalogProduct.name_zh)
            .filter(CatalogProduct.review_status == "approved")
            .all()
        )
        counts: dict[str, int] = {}
        for cat_id, _ in rows:
            counts[cat_id] = counts.get(cat_id, 0) + 1
        names = {
            "vegetable": ("蔬菜", "Vegetables"),
            "meat": ("肉类", "Meat"),
            "seafood": ("水产", "Seafood"),
            "fruit": ("水果", "Fruit"),
            "condiment": ("调味品", "Condiments"),
            "baking": ("烘焙原料", "Baking"),
            "staple": ("粮油米面", "Staples"),
            "dairy": ("乳品", "Dairy"),
            "beverage": ("饮料", "Beverages"),
        }
        result = []
        for cat_id, count in sorted(counts.items()):
            zh, en = names.get(cat_id, (cat_id, cat_id))
            result.append({"id": cat_id, "name": en, "name_zh": zh, "product_count": count})
        return result

    def search_products(
        self,
        *,
        q: str | None = None,
        category_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
        approved_only: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        quarantined = self._quarantined_barcodes()
        query = self.db.query(CatalogProduct)
        if approved_only:
            query = query.filter(CatalogProduct.review_status == "approved")
        if category_id:
            query = query.filter(CatalogProduct.category_id == category_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    CatalogProduct.name.ilike(like),
                    CatalogProduct.name_zh.ilike(like),
                    CatalogProduct.brand.ilike(like),
                )
            )
        products = query.order_by(CatalogProduct.sku_id).all()
        products = [p for p in products if p.source_barcode not in quarantined]
        total = len(products)
        page_products = products[(page - 1) * page_size : page * page_size]
        items = []
        for p in page_products:
            offer = (
                self.db.query(Offer)
                .filter_by(store_id=self.store_id, sku_id=p.sku_id)
                .first()
            )
            items.append(product_to_dict(p, offer))
        return items, total

    def get_product(self, sku_id: str) -> dict[str, Any] | None:
        p = self.db.get(CatalogProduct, sku_id)
        if not p or p.review_status != "approved":
            return None
        if p.source_barcode in self._quarantined_barcodes():
            return None
        offer = (
            self.db.query(Offer)
            .filter_by(store_id=self.store_id, sku_id=sku_id)
            .first()
        )
        data = product_to_dict(p, offer)
        from app.services.delivery_service import DeliveryService

        delivery = DeliveryService(self.db).get_quote(self.store_id)
        data["delivery_eta_minutes"] = delivery.get("eta_minutes")
        return data

    def list_sellable_products(self, *, store_id: str | None = None) -> list[dict[str, Any]]:
        """Approved, non-quarantined, sellable SKUs for the store.

        One query for products and one for offers instead of a query per row, so
        scenario building stays a single pass over a small demo catalog.
        """
        store = store_id or self.store_id
        quarantined = self._quarantined_barcodes()
        products = [
            p
            for p in self.db.query(CatalogProduct)
            .filter(CatalogProduct.review_status == "approved")
            .all()
            if p.source_barcode not in quarantined
        ]
        offers = {
            offer.sku_id: offer
            for offer in self.db.query(Offer).filter_by(store_id=store).all()
        }
        result: list[dict[str, Any]] = []
        for product in products:
            offer = offers.get(product.sku_id)
            if not offer or not offer.sellable:
                continue
            result.append(product_to_dict(product, offer))
        return result

    def get_candidates(
        self,
        *,
        category_id: str | None = None,
        ingredient_ids: list[str] | None = None,
        keywords: list[str] | None = None,
        usage: str | None = None,
        product_type: str | None = None,
        spec_size: str | None = None,
        excluded_ingredients: list[str] | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        quarantined = self._quarantined_barcodes()
        query = self.db.query(CatalogProduct).filter(
            CatalogProduct.review_status == "approved"
        )
        if category_id:
            query = query.filter(CatalogProduct.category_id == category_id)
        if product_type:
            query = query.filter(CatalogProduct.product_type == product_type)
        products = [
            p for p in query.order_by(CatalogProduct.sku_id).all()
            if p.source_barcode not in quarantined
        ]
        items = []
        for product in products:
            offer = (
                self.db.query(Offer)
                .filter_by(store_id=self.store_id, sku_id=product.sku_id)
                .first()
            )
            if not offer or not offer.sellable:
                continue
            items.append(product_to_dict(product, offer))

        filtered: list[dict[str, Any]] = []
        for item in items:
            if ingredient_ids:
                ids = set(item.get("ingredient_ids", []))
                if not ids.intersection(ingredient_ids):
                    continue
            text = f"{item.get('name','')} {item.get('name_zh','')}"
            if usage:
                tags = item.get("usage_tags", [])
                usage_ok = (
                    usage in tags
                    or usage in (item.get("name_zh") or "")
                    or usage in text
                )
                if not usage_ok and keywords:
                    if not any(k in text for k in keywords):
                        continue
            elif keywords:
                if not any(k.lower() in text.lower() for k in keywords):
                    continue
            if product_type and item.get("product_type") != product_type:
                continue
            if product_type == "flour" and item.get("product_type") == "leavening":
                continue
            if excluded_ingredients:
                ids = set(item.get("ingredient_ids", []))
                if ids.intersection(excluded_ingredients):
                    continue
            if spec_size == "small":
                from app.services.validation_context import ValidationContext
                from app.agent.state import Requirements

                ctx = ValidationContext.from_requirements(
                    Requirements(specification={"size": "small"}),
                    store_id=self.store_id,
                    delivery_zone_id="zone-default",
                )
                if not ctx.matches_spec(item):
                    continue
            filtered.append(item)
        return filtered[:max_results]

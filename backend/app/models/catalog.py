"""Catalog ORM models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    sku_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_barcode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ingredient_ids: Mapped[str] = mapped_column(Text, default="[]")
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="catalog")
    review_status: Mapped[str] = mapped_column(String(32), default="approved", index=True)
    spec_quantity: Mapped[float | None] = mapped_column(nullable=True)
    spec_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    usage_tags: Mapped[str] = mapped_column(Text, default="[]")
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CatalogReview(Base):
    __tablename__ = "catalog_reviews"

    source_barcode: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    corrected_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingredient_ids: Mapped[str] = mapped_column(Text, default="[]")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_version: Mapped[str] = mapped_column(String(16), default="v1")


class PurchaseTemplate(Base):
    __tablename__ = "purchase_templates"

    template_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(128), nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    base_people: Mapped[int] = mapped_column(Integer, default=2)
    required_items: Mapped[str] = mapped_column(Text, nullable=False)
    optional_items: Mapped[str] = mapped_column(Text, default="[]")
    pantry_items: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(64), default="fixture")

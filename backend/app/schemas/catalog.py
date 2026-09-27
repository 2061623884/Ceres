"""Catalog API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    id: str
    name: str
    name_zh: str
    product_count: int = 0


class ProductSummary(BaseModel):
    sku_id: str
    name: str
    name_zh: str | None = None
    category_id: str
    brand: str | None = None
    image_path: str | None = None
    price_fen: int | None = None
    available_qty: int | None = None
    sellable: bool = True
    source: str = "catalog"
    review_status: str = "approved"
    metadata: dict = Field(default_factory=dict)


class ProductDetail(ProductSummary):
    spec_quantity: float | None = None
    spec_unit: str | None = None
    usage_tags: list[str] = Field(default_factory=list)
    ingredient_ids: list[str] = Field(default_factory=list)
    delivery_eta_minutes: int | None = None


class ProductListResponse(BaseModel):
    items: list[ProductSummary]
    total: int
    page: int
    page_size: int

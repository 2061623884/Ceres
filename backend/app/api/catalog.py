"""Catalog API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.catalog import CategoryResponse, ProductDetail, ProductListResponse, ProductSummary
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    svc = CatalogService(db)
    return svc.get_categories()


@router.get("/products", response_model=ProductListResponse)
def list_products(
    q: str | None = None,
    category_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
):
    svc = CatalogService(db)
    items, total = svc.search_products(q=q, category_id=category_id, page=page, page_size=page_size)
    return ProductListResponse(
        items=[ProductSummary(**i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/products/{sku_id}", response_model=ProductDetail)
def get_product(sku_id: str, db: Session = Depends(get_db)):
    from app.core.errors import AppError

    svc = CatalogService(db)
    product = svc.get_product(sku_id)
    if not product:
        raise AppError(404, "INVALID_INPUT", f"Product {sku_id} not found")
    return ProductDetail(**product)

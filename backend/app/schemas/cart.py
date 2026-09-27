"""Cart API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CartItemResponse(BaseModel):
    sku_id: str
    name: str
    quantity: int
    unit_price_fen: int
    line_total_fen: int
    image_path: str | None = None
    sellable: bool = True


class CartResponse(BaseModel):
    store_id: str
    version: int
    items: list[CartItemResponse]
    total_price_fen: int
    business_data_mode: str


class CartItemAddRequest(BaseModel):
    sku_id: str
    quantity: int = Field(..., ge=1, le=99)
    expected_cart_version: int = Field(default=0, ge=0)


class CartItemPatchRequest(BaseModel):
    quantity: int = Field(..., ge=0, le=99)
    expected_cart_version: int = Field(..., ge=0)


class CartOperationResponse(BaseModel):
    operation_id: str
    status: str
    cart_version: int
    items_added: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)

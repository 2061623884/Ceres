"""Cart API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import get_or_create_owner
from app.schemas.cart import (
    CartCheckoutRequest,
    CartItemAddRequest,
    CartItemPatchRequest,
    CartOperationResponse,
    CartResponse,
)
from app.services.cart_service import CartService

router = APIRouter(prefix="/api/v1", tags=["cart"])


def _owner(request: Request, response: Response, db: Session) -> str:
    return get_or_create_owner(request, response, db)


@router.get("/cart", response_model=CartResponse)
def get_cart(request: Request, response: Response, db: Session = Depends(get_db)):
    owner_id = _owner(request, response, db)
    cart = CartService(db, owner_id).get_cart()
    return CartResponse(**cart)


@router.post("/cart/items", response_model=CartResponse)
def add_cart_item(
    body: CartItemAddRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    cart = CartService(db, owner_id).add_item(
        body.sku_id, body.quantity, body.expected_cart_version
    )
    return CartResponse(**cart)


@router.post("/cart/checkout")
def checkout_cart(body: CartCheckoutRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    owner_id = _owner(request, response, db)
    return CartService(db, owner_id).checkout(body.expected_cart_version)


@router.patch("/cart/items/{sku_id}", response_model=CartResponse)
def patch_cart_item(
    sku_id: str,
    body: CartItemPatchRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    cart = CartService(db, owner_id).update_item(
        sku_id, body.quantity, body.expected_cart_version
    )
    return CartResponse(**cart)


@router.delete("/cart/items/{sku_id}", response_model=CartResponse)
def delete_cart_item(
    sku_id: str,
    expected_cart_version: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    cart = CartService(db, owner_id).remove_item(sku_id, expected_cart_version)
    return CartResponse(**cart)


@router.get("/cart/operations/{operation_id}", response_model=CartOperationResponse)
def get_operation(
    operation_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    from app.core.errors import AppError

    owner_id = _owner(request, response, db)
    result = CartService(db, owner_id).get_operation(operation_id)
    if not result:
        raise AppError(404, "INVALID_INPUT", "Operation not found")
    return CartOperationResponse(**result)

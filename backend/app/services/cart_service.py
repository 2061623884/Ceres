"""Cart operations with versioning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cart import Cart, CartItem, CartOperation
from app.models.catalog import CatalogProduct
from app.services.offer_service import OfferService


class CartService:
    def __init__(self, db: Session, owner_id: str, store_id: str = "store-demo-01"):
        self.db = db
        self.owner_id = owner_id
        self.store_id = store_id
        self.offers = OfferService(db, store_id)

    def _get_or_create_cart(self) -> Cart:
        cart = self.db.query(Cart).filter_by(owner_id=self.owner_id).first()
        if cart:
            return cart
        cart = Cart(owner_id=self.owner_id, store_id=self.store_id, version=1)
        self.db.add(cart)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            cart = self.db.query(Cart).filter_by(owner_id=self.owner_id).first()
            if not cart:
                raise
        return cart

    def _cart_qty(self, cart_id: int, sku_id: str) -> int:
        item = self.db.query(CartItem).filter_by(cart_id=cart_id, sku_id=sku_id).first()
        return item.quantity if item else 0

    def quantities_for(self, sku_ids: list[str]) -> dict[str, int]:
        """How many of each SKU this owner already has in *their own* cart.

        Read-only: it never creates a cart. Scoped by owner (and store) through
        the cart row, because summing ``CartItem`` by SKU alone would let another
        owner's cart reduce this shopper's stock headroom.
        """
        wanted = {sku for sku in sku_ids if sku}
        if not wanted:
            return {}
        rows = (
            self.db.query(CartItem.sku_id, func.sum(CartItem.quantity))
            .join(Cart, Cart.id == CartItem.cart_id)
            .filter(
                Cart.owner_id == self.owner_id,
                CartItem.sku_id.in_(wanted),
            )
        )
        if self.store_id:
            rows = rows.filter(Cart.store_id == self.store_id)
        return {sku_id: int(total or 0) for sku_id, total in rows.group_by(CartItem.sku_id).all()}

    def _assert_sellable(self, sku_id: str) -> None:
        product = self.db.get(CatalogProduct, sku_id)
        offer = self.offers.get_offer(sku_id)
        if not product or product.review_status != "approved":
            raise AppError(422, "PRODUCT_UNAVAILABLE", f"Product {sku_id} unavailable")
        if not offer or not offer.sellable:
            raise AppError(422, "PRODUCT_UNAVAILABLE", f"Product {sku_id} unavailable")

    def _assert_stock(self, cart: Cart, sku_id: str, qty: int, *, mode: str = "add") -> None:
        if qty <= 0:
            raise AppError(422, "PRODUCT_UNAVAILABLE", "Quantity must be positive")
        self._assert_sellable(sku_id)
        offer = self.offers.get_offer(sku_id)
        assert offer is not None
        in_cart = self._cart_qty(cart.id, sku_id)
        required = qty if mode == "set" else in_cart + qty
        if required > offer.available_qty:
            raise AppError(422, "PRODUCT_UNAVAILABLE", "Insufficient stock")

    def _bump_cart_version(self, cart: Cart, expected_version: int | None) -> int:
        if expected_version is not None and cart.version != expected_version:
            raise AppError(409, "STALE_STATE", "Cart version mismatch", state_version=cart.version)
        new_version = cart.version + 1
        stmt = (
            update(Cart)
            .where(Cart.id == cart.id, Cart.version == cart.version)
            .values(version=new_version, updated_at=datetime.now(timezone.utc))
        )
        if self.db.execute(stmt).rowcount != 1:
            raise AppError(409, "STALE_STATE", "Cart version mismatch", state_version=cart.version)
        cart.version = new_version
        return new_version

    def _apply_items(self, cart: Cart, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        added: list[dict[str, Any]] = []
        for item in items:
            sku_id = item["sku_id"]
            qty = item["quantity"]
            self._assert_stock(cart, sku_id, qty, mode="add")
            offer = self.offers.get_offer(sku_id)
            assert offer is not None
            existing = (
                self.db.query(CartItem)
                .filter_by(cart_id=cart.id, sku_id=sku_id)
                .first()
            )
            if existing:
                existing.quantity += qty
                existing.unit_price_fen = offer.price_fen
            else:
                self.db.add(
                    CartItem(
                        cart_id=cart.id,
                        sku_id=sku_id,
                        quantity=qty,
                        unit_price_fen=offer.price_fen,
                    )
                )
            added.append({"sku_id": sku_id, "quantity": qty})
        return added

    def get_cart(self) -> dict[str, Any]:
        cart = self._get_or_create_cart()
        items = self.db.query(CartItem).filter_by(cart_id=cart.id).all()
        result_items = []
        total = 0
        for item in items:
            product = self.db.get(CatalogProduct, item.sku_id)
            offer = self.offers.get_offer(item.sku_id)
            sellable = bool(offer and offer.sellable)
            line_total = item.unit_price_fen * item.quantity
            total += line_total
            result_items.append(
                {
                    "sku_id": item.sku_id,
                    "name": (product.name_zh or product.name) if product else item.sku_id,
                    "quantity": item.quantity,
                    "unit_price_fen": item.unit_price_fen,
                    "line_total_fen": line_total,
                    "image_path": product.image_path if product else None,
                    "sellable": sellable,
                }
            )
        from app.core.config import get_settings

        return {
            "store_id": cart.store_id,
            "version": cart.version,
            "items": result_items,
            "total_price_fen": total,
            "business_data_mode": get_settings().business_data_mode,
        }

    def add_item(self, sku_id: str, quantity: int, expected_version: int = 0) -> dict:
        cart = self._get_or_create_cart()
        if expected_version and cart.version != expected_version:
            raise AppError(409, "STALE_STATE", "Cart version mismatch", state_version=cart.version)
        self._assert_stock(cart, sku_id, quantity, mode="add")
        offer = self.offers.get_offer(sku_id)
        assert offer is not None
        existing = (
            self.db.query(CartItem)
            .filter_by(cart_id=cart.id, sku_id=sku_id)
            .first()
        )
        if existing:
            existing.quantity += quantity
            existing.unit_price_fen = offer.price_fen
        else:
            self.db.add(
                CartItem(
                    cart_id=cart.id,
                    sku_id=sku_id,
                    quantity=quantity,
                    unit_price_fen=offer.price_fen,
                )
            )
        self._bump_cart_version(cart, expected_version if expected_version else None)
        self.db.commit()
        return self.get_cart()

    def update_item(self, sku_id: str, quantity: int, expected_version: int) -> dict:
        cart = self._get_or_create_cart()
        if cart.version != expected_version:
            raise AppError(409, "STALE_STATE", "Cart version mismatch", state_version=cart.version)
        item = self.db.query(CartItem).filter_by(cart_id=cart.id, sku_id=sku_id).first()
        if quantity == 0:
            if item:
                self.db.delete(item)
        elif item:
            self._assert_stock(cart, sku_id, quantity, mode="set")
            offer = self.offers.get_offer(sku_id)
            item.quantity = quantity
            if offer:
                item.unit_price_fen = offer.price_fen
        else:
            raise AppError(404, "INVALID_INPUT", "Item not in cart")
        self._bump_cart_version(cart, expected_version)
        self.db.commit()
        return self.get_cart()

    def remove_item(self, sku_id: str, expected_version: int) -> dict:
        return self.update_item(sku_id, 0, expected_version)

    @staticmethod
    def digest_request(data: dict) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def apply_confirm_items(
        self,
        items: list[dict[str, Any]],
        *,
        expected_cart_version: int | None = None,
    ) -> dict[str, Any]:
        cart = self._get_or_create_cart()
        if expected_cart_version is not None and cart.version != expected_cart_version:
            raise AppError(409, "STALE_STATE", "Cart version mismatch", state_version=cart.version)
        added = self._apply_items(cart, items)
        cart_version = self._bump_cart_version(cart, cart.version)
        return {
            "cart_version": cart_version,
            "items_added": added,
        }

    def add_from_plan(
        self,
        items: list[dict[str, Any]],
        idempotency_key: str,
        request_digest: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        existing = (
            self.db.query(CartOperation)
            .filter_by(owner_id=self.owner_id, idempotency_key=idempotency_key)
            .first()
        )
        if existing:
            if existing.request_digest != request_digest:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key conflict")
            if existing.status == "completed" and existing.result_json:
                return json.loads(existing.result_json)
            if existing.status == "pending":
                raise AppError(409, "TURN_IN_PROGRESS", "Operation in progress")

        operation_id = f"op-{uuid4().hex[:12]}"
        op = CartOperation(
            operation_id=operation_id,
            owner_id=self.owner_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            status="pending",
            task_id=task_id,
        )
        self.db.add(op)
        self.db.flush()

        try:
            applied = self.apply_confirm_items(items)
            result = {
                "operation_id": operation_id,
                "status": "completed",
                "cart_version": applied["cart_version"],
                "items_added": applied["items_added"],
                "errors": [],
            }
            op.status = "completed"
            op.result_json = json.dumps(result)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def get_operation(self, operation_id: str) -> dict | None:
        op = self.db.get(CartOperation, operation_id)
        if not op or op.owner_id != self.owner_id:
            return None
        if op.result_json:
            return json.loads(op.result_json)
        return {"operation_id": operation_id, "status": op.status}

"""Plan confirmation with idempotency-before-version."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.state import Requirements
from app.core.config import get_settings
from app.core.errors import AppError
from app.models.cart import CartOperation
from app.models.catalog import CatalogProduct
from app.models.session import GuideSession, GuideTask
from app.schemas.guide import ConfirmItem, EntryContext
from app.services.cart_service import CartService
from app.services.catalog_service import product_to_dict
from app.services.conversation_service import ConversationService
from app.services.delivery_service import DeliveryService
from app.services.operation_service import OperationService
from app.services.trace_service import TraceService
from app.services.validation_context import ValidationContext


class ConfirmationService:
    def __init__(
        self,
        db: Session,
        owner_id: str,
        store_id: str = "store-demo-01",
        delivery_zone_id: str = "zone-default",
    ):
        self.db = db
        self.owner_id = owner_id
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.cart = CartService(db, owner_id, store_id)
        self.trace = TraceService(db)
        self.conversation = ConversationService(db, owner_id)
        self.operations = OperationService(db, owner_id)

    def _parse_expires_at(self, value: str) -> datetime:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at

    def _normalize_selected_items(
        self, selected_items: list[dict[str, Any]] | list[ConfirmItem]
    ) -> list[ConfirmItem]:
        normalized: list[ConfirmItem] = []
        for item in selected_items:
            if isinstance(item, ConfirmItem):
                normalized.append(item)
            else:
                normalized.append(ConfirmItem(**item))
        seen: set[str] = set()
        for item in normalized:
            if item.sku_id in seen:
                raise AppError(422, "INVALID_INPUT", "Duplicate SKU in confirmation")
            seen.add(item.sku_id)
        return normalized

    def _cart_snapshot(self) -> dict[str, Any]:
        cart = self.cart.get_cart()
        return {
            "version": cart.get("version"),
            "items": [
                {"sku_id": i["sku_id"], "quantity": i["quantity"]}
                for i in cart.get("items", [])
            ],
        }

    def _action_message(self, result: dict[str, Any]) -> str:
        items = ", ".join(
            f"{item['quantity']}件 {item['sku_id']}" for item in result["items_added"]
        )
        return f"已加入购物车：{items}（购物车版本 {result['cart_version']}）"

    def _assert_cart_unchanged(self, before: dict[str, Any]) -> None:
        after = self._cart_snapshot()
        if before["version"] != after["version"] or before["items"] != after["items"]:
            raise AppError(500, "INTERNAL_ERROR", "Cart mutated on failed confirm")

    def _validate_snapshot(
        self,
        plan: dict[str, Any],
        selected: list[ConfirmItem],
        requirements: Requirements,
        ctx: ValidationContext,
    ) -> list[dict[str, Any]]:
        plan_items = {item["sku_id"]: item for item in plan.get("items", [])}
        selected_map = {item.sku_id: item.quantity for item in selected}

        if plan.get("validation_status") == "stale_supply":
            raise AppError(409, "STALE_SUPPLY", "Supply context changed, refresh required")
        if plan.get("can_confirm") is False:
            raise AppError(422, "CONSTRAINT_UNSATISFIED", "Plan cannot be confirmed")
        if plan.get("coverage_mode") == "uncovered":
            raise AppError(422, "CONSTRAINT_UNSATISFIED", "Coverage incomplete")

        # Every row's *outstanding* quantity, whether it is ticked or not: an
        # alternative may legitimately be chosen from an unticked row, and a row
        # already written by an explicit click has nothing left to buy.
        outstanding: dict[str, int] = {}
        for sku, row in plan_items.items():
            if row.get("role", "required") not in ("required", "pantry", "optional"):
                continue
            remaining = int(row.get("quantity") or 1) - int(row.get("added_quantity") or 0)
            if remaining > 0:
                outstanding[sku] = remaining
        if plan.get("mode") == "alternatives":
            if len(selected_map) != 1:
                raise AppError(422, "CONSTRAINT_UNSATISFIED", "Select exactly one alternative")
        else:
            expected_skus = {
                sku
                for sku, row in plan_items.items()
                if row.get("selected", True) and outstanding.get(sku, 0) > 0
            }
            selected_set = set(selected_map.keys())
            if expected_skus != selected_set:
                raise AppError(
                    422,
                    "CONSTRAINT_UNSATISFIED",
                    "Must confirm exactly the selected snapshot items",
                )

        validated: list[dict[str, Any]] = []
        selected_total = 0
        for sku_id, qty in selected_map.items():
            if sku_id not in plan_items:
                raise AppError(422, "CONSTRAINT_UNSATISFIED", f"SKU {sku_id} not in plan")
            snapshot = plan_items[sku_id]
            # Never fall back to the original plan quantity: a row that is already
            # in the cart would be bought a second time.
            expected_qty = outstanding.get(sku_id)
            if expected_qty is None:
                raise AppError(
                    422,
                    "CONSTRAINT_UNSATISFIED",
                    f"SKU {sku_id} has nothing outstanding to confirm",
                )
            if expected_qty != qty:
                raise AppError(422, "CONSTRAINT_UNSATISFIED", f"Quantity mismatch for {sku_id}")
            offer = self.cart.offers.get_offer(sku_id)
            if not offer or not offer.sellable:
                raise AppError(422, "PRODUCT_UNAVAILABLE", f"SKU {sku_id} unavailable")
            if offer.price_fen != snapshot["unit_price_fen"]:
                raise AppError(409, "PRICE_CHANGED", "Price changed, reconfirm required")
            if ctx.specification:
                product = self.db.get(CatalogProduct, sku_id)
                if not ctx.matches_spec(product_to_dict(product, offer)):
                    product_size = (
                        f"{product.spec_quantity}{product.spec_unit}"
                        if product.spec_quantity is not None and product.spec_unit
                        else "规格信息不完整"
                    )
                    raise AppError(
                        422,
                        "CONSTRAINT_UNSATISFIED",
                        f"商品「{product.name_zh or product.name or sku_id}」当前规格为 {product_size}，"
                        + ("不符合小包装要求" if ctx.specification.get("size") == "small"
                           else "不符合指定的商品筛选条件") + "，请刷新清单后再确认。",
                        detail=f"SKU {sku_id} violates specification {ctx.specification}",
                    )
            selected_total += offer.price_fen * qty
            validated.append({"sku_id": sku_id, "quantity": qty})

        if requirements.budget_fen is not None and selected_total > requirements.budget_fen:
            raise AppError(
                422,
                "CONSTRAINT_UNSATISFIED",
                # Customer-facing wording: money is never shown in the internal unit.
                f"待确认合计 {selected_total / 100:.2f} 元，超出你说的预算 "
                f"{requirements.budget_fen / 100:.2f} 元。",
            )

        return validated

    def _claim_execution(self, task_id: str, expected_state_version: int) -> GuideTask:
        claimed = self.db.execute(
            text(
                """
                UPDATE guide_tasks
                SET current_step = 'adding_to_cart'
                WHERE task_id = :task_id
                  AND owner_id = :owner_id
                  AND status = 'active'
                  AND current_step = 'awaiting_confirmation'
                  AND state_version = :version
                  AND user_confirmed = 0
                """
            ),
            {
                "task_id": task_id,
                "owner_id": self.owner_id,
                "version": expected_state_version,
            },
        )
        if claimed.rowcount != 1:
            task = self.db.get(GuideTask, task_id)
            if task and task.user_confirmed:
                raise AppError(409, "STALE_STATE", "Task already completed", task_id=task_id)
            raise AppError(
                409,
                "STALE_STATE",
                "Could not claim task execution",
                task_id=task_id,
                state_version=task.state_version if task else expected_state_version,
            )
        task = self.db.get(GuideTask, task_id)
        if not task:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        return task

    def confirm(
        self,
        task_id: str,
        plan_id: str,
        plan_version: int,
        expected_state_version: int,
        selected_items: list[dict[str, Any]] | list[ConfirmItem],
        idempotency_key: str,
        request_digest: str,
        expected_session_version: int | None = None,
    ) -> dict[str, Any]:
        cart_before = self._cart_snapshot()
        try:
            result, action_message, session_id, executed = self.confirm_core(
                task_id=task_id,
                plan_id=plan_id,
                plan_version=plan_version,
                expected_state_version=expected_state_version,
                selected_items=selected_items,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                expected_session_version=expected_session_version,
            )
            if not executed:
                return result
            self.conversation.save_message(
                session_id,
                task_id=task_id,
                role="assistant",
                kind="action_result",
                content=action_message,
                request_id=idempotency_key,
                plan_id=plan_id,
                plan_version=plan_version,
            )
            self.db.commit()
            return result
        except AppError:
            self._assert_cart_unchanged(cart_before)
            self.db.rollback()
            raise
        except Exception as exc:
            self._assert_cart_unchanged(cart_before)
            self.db.rollback()
            raise AppError(500, "INTERNAL_ERROR", str(exc), retryable=True) from exc

    def confirm_core(
        self,
        task_id: str,
        plan_id: str,
        plan_version: int,
        expected_state_version: int,
        selected_items: list[dict[str, Any]] | list[ConfirmItem],
        idempotency_key: str,
        request_digest: str,
        expected_session_version: int | None = None,
    ) -> tuple[dict[str, Any], str | None, str | None, bool]:
        cart_before = self._cart_snapshot()

        op = (
            self.db.query(CartOperation)
            .filter_by(owner_id=self.owner_id, idempotency_key=idempotency_key)
            .first()
        )
        if op:
            if op.request_digest != request_digest:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key conflict")
            if op.status == "completed" and op.result_json:
                guide_op = self.operations.find("confirm", task_id, idempotency_key)
                if guide_op and guide_op.result_json:
                    result = json.loads(guide_op.result_json)
                    return result, self._action_message(result), None, False
                result = json.loads(op.result_json)
                return result, self._action_message(result), None, False
            if op.status == "pending":
                raise AppError(409, "TURN_IN_PROGRESS", "Confirmation in progress")

        guide_cached = self.operations.check_or_begin(
            "confirm", "task", task_id, idempotency_key, request_digest, "TURN_IN_PROGRESS"
        )
        if guide_cached and guide_cached.result_json:
            result = json.loads(guide_cached.result_json)
            return result, self._action_message(result), None, False

        pre_task = self.db.get(GuideTask, task_id)
        if not pre_task or pre_task.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        session = self.db.get(GuideSession, pre_task.session_id)
        if not session:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
        if session.current_task_id != task_id:
            raise AppError(409, "STALE_STATE", "Not current task", task_id=task_id)
        if expected_session_version is not None and expected_session_version != session.session_version:
            raise AppError(
                409,
                "STALE_STATE",
                "Session version mismatch",
                session_version=session.session_version,
            )
        entry = EntryContext(**json.loads(session.entry_context_json))
        self.store_id = entry.store_id
        self.delivery_zone_id = entry.delivery_zone_id
        self.cart = CartService(self.db, self.owner_id, self.store_id)
        cart = self.cart.get_cart()
        if cart.get("store_id") and cart.get("store_id") != self.store_id:
            raise AppError(409, "STORE_MISMATCH", "Cart store mismatch")

        plan = json.loads(pre_task.plan_json) if pre_task.plan_json else None
        if not plan or plan["plan_id"] != plan_id or plan["plan_version"] != plan_version:
            self._assert_cart_unchanged(cart_before)
            raise AppError(409, "STALE_PLAN", "Plan version mismatch", task_id=task_id)

        expires_at = self._parse_expires_at(plan["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            self._assert_cart_unchanged(cart_before)
            raise AppError(409, "PLAN_EXPIRED", "Plan expired", task_id=task_id)

        if not DeliveryService(self.db).check_delivery(self.store_id, self.delivery_zone_id):
            self._assert_cart_unchanged(cart_before)
            raise AppError(422, "CONSTRAINT_UNSATISFIED", "Delivery not reachable")

        req = json.loads(pre_task.requirements_json or "{}")
        requirements = Requirements.from_dict(req)
        ctx = ValidationContext.from_requirements(
            requirements,
            store_id=self.store_id,
            delivery_zone_id=self.delivery_zone_id,
        )
        normalized = self._normalize_selected_items(selected_items)
        try:
            validated_items = self._validate_snapshot(plan, normalized, requirements, ctx)
        except AppError:
            self._assert_cart_unchanged(cart_before)
            raise

        task = self._claim_execution(task_id, expected_state_version)

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
            applied = self.cart.apply_confirm_items(validated_items)
            task.user_confirmed = True
            task.confirmation_id = f"conf-{uuid4().hex[:8]}"
            task.current_step = "completed"
            task.status = "completed"
            task.state_version += 1
            task.updated_at = datetime.now(timezone.utc)
            session.session_version += 1

            result = {
                "operation_id": operation_id,
                "status": "completed",
                "cart_version": applied["cart_version"],
                "items_added": applied["items_added"],
                "errors": [],
                "task_id": task_id,
                "state_version": task.state_version,
                "confirmation_id": task.confirmation_id,
            }
            task.cart_result_json = json.dumps(result)
            op.status = "completed"
            op.result_json = json.dumps(result)

            action_msg = self._action_message(applied)
            settings = get_settings()
            self.trace.record_event(
                self.owner_id,
                "plan_confirmed",
                {"plan_id": plan_id, "confirmation_id": task.confirmation_id},
                session_id=task.session_id,
                task_id=task_id,
                model_mode=settings.llm_mode,
                source="server",
            )
            self.trace.record_event(
                self.owner_id,
                "cart_add_succeeded",
                {"items_added": applied["items_added"], "cart_version": applied["cart_version"]},
                session_id=task.session_id,
                task_id=task_id,
                model_mode=settings.llm_mode,
                source="server",
            )
            guide_op = self.operations.find("confirm", task_id, idempotency_key)
            if guide_op:
                self.operations.complete(guide_op, result)
            return result, action_msg, session.session_id, True
        except AppError:
            task.current_step = "awaiting_confirmation"
            self._assert_cart_unchanged(cart_before)
            raise
        except Exception as exc:
            task.current_step = "awaiting_confirmation"
            self._assert_cart_unchanged(cart_before)
            raise AppError(500, "INTERNAL_ERROR", str(exc), retryable=True) from exc

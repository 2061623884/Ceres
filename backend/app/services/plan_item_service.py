"""Explicit per-row cart writes from an editable plan.

The batch confirm is not the only way into the cart any more: a shopper may tick
one row and add just that one. That path must not become a second, weaker door:

* ownership, session/state version, plan version, expiry, price, stock, delivery
  and sellability are all checked exactly as the batch confirm checks them;
* a row already added on its own is recorded on the plan, so the later batch
  confirm cannot buy it a second time;
* the task is claimed for the duration of the write, so a revision or a confirm
  racing the same row is rejected rather than interleaved;
* the write is idempotent per request id, and a retry returns the first result
  instead of adding twice.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cart import CartOperation
from app.models.session import GuideSession, GuideTask
from app.services import plan_contract as contract
from app.services.cart_service import CartService
from app.services.conversation_service import ConversationService
from app.services.delivery_service import DeliveryService
from app.services.operation_service import OperationService
from app.services.session_actions import effective_status

OP_TYPE = "item_add"


class PlanItemService:
    def __init__(self, db: Session, owner_id: str, store_id: str, delivery_zone_id: str):
        self.db = db
        self.owner_id = owner_id
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.cart = CartService(db, owner_id, store_id)
        self.conversation = ConversationService(db, owner_id)
        self.operations = OperationService(db, owner_id)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _outstanding(plan: dict) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in plan.get("items") or []:
            if not item.get("selected", True):
                continue
            remaining = int(item.get("quantity") or 1) - int(item.get("added_quantity") or 0)
            if remaining > 0:
                result[str(item["sku_id"])] = remaining
        return result

    def _recompute(self, plan: dict) -> dict:
        outstanding = self._outstanding(plan)
        plan["outstanding_total_fen"] = sum(
            int(item.get("unit_price_fen") or 0) * outstanding[str(item["sku_id"])]
            for item in plan.get("items") or []
            if str(item.get("sku_id")) in outstanding
        )
        items = plan.get("items") or []
        gaps = contract.collect_gaps(plan.get("gaps"), items)
        coverage = contract.coverage(items, gaps, plan.get("coverage_intent"))
        plan["gaps"] = gaps
        plan["uncovered_items"] = coverage["uncovered_items"]
        plan["coverage_mode"] = coverage["coverage_mode"]
        plan["coverage_intent"] = coverage["coverage_intent"]
        # A per-row add never clears a supply gap, and a row already bought has
        # nothing left to confirm.
        plan["can_confirm"] = (
            bool(outstanding)
            and not coverage["over_stock"]
            and coverage["coverage_mode"] != "uncovered"
        )
        return plan

    def _assert_cart_store_matches(self) -> None:
        """Refuse to write into a cart that belongs to another store.

        ``CartService`` resolves the cart by owner only, so a shopper who already
        has a cart from store B would otherwise receive store A's item in it — the
        batch confirmation already rejects this, and the row path must too.
        """
        cart = self.cart.get_cart()
        cart_store = cart.get("store_id")
        if cart_store and cart_store != self.store_id:
            raise AppError(409, "STORE_MISMATCH", "Cart store mismatch")

    def _assert_within_budget(
        self,
        plan: dict[str, Any],
        row: dict[str, Any],
        quantity: int,
        requirements_json: str | None,
    ) -> None:
        """Enforce the shopper's explicit budget before writing.

        Deliberately *not* a blanket ``can_confirm`` gate: an optional row in an
        open scenario, or a plan whose selected rows are already bought, is
        legitimately purchasable through an explicit click. The stated budget is
        what actually constrains the write, and money in the message is yuan.
        """
        requirements = json.loads(requirements_json or "{}")
        budget_fen = requirements.get("budget_fen")
        if budget_fen is None:
            return
        projected = 0
        for item in plan.get("items") or []:
            if not item.get("selected", True):
                continue
            wanted = int(item.get("quantity") or 1)
            if str(item.get("sku_id")) == str(row.get("sku_id")):
                wanted = int(row.get("added_quantity") or 0) + quantity
            projected += int(item.get("unit_price_fen") or 0) * wanted
        if projected > int(budget_fen):
            raise AppError(
                422,
                "CONSTRAINT_UNSATISFIED",
                f"这件商品会让待确认合计达到 {projected / 100:.2f} 元，超出你说的预算 "
                f"{int(budget_fen) / 100:.2f} 元。",
            )

    def _claim_task(self, task_id: str, expected_state_version: int) -> GuideTask:
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
            raise AppError(
                409,
                "STALE_STATE",
                "Could not claim task for item add",
                task_id=task_id,
                state_version=task.state_version if task else expected_state_version,
            )
        task = self.db.get(GuideTask, task_id)
        if not task:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        # The claim ran as raw SQL, so the ORM's cached copy is stale. Refresh it:
        # otherwise a later "set current_step back" would look like a no-op and
        # the task would stay claimed.
        self.db.refresh(task)
        return task

    # --------------------------------------------------------------------- add

    def add_item(
        self,
        task_id: str,
        *,
        sku_id: str,
        quantity: int,
        request_id: str,
        expected_state_version: int,
        expected_session_version: int | None = None,
    ) -> dict:
        digest = CartService.digest_request(
            {
                "sku_id": sku_id,
                "quantity": quantity,
                "expected_state_version": expected_state_version,
                "expected_session_version": expected_session_version,
            }
        )
        cached = self.operations.check_or_begin(
            OP_TYPE, "task", task_id, request_id, digest, "TURN_IN_PROGRESS"
        )
        if cached and cached.result_json:
            return json.loads(cached.result_json)

        task = self.db.get(GuideTask, task_id)
        if not task or task.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        session = self.db.get(GuideSession, task.session_id)
        if not session or session.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
        if session.current_task_id != task_id:
            raise AppError(409, "STALE_STATE", "Not current task", task_id=task_id)
        if (
            expected_session_version is not None
            and expected_session_version != session.session_version
        ):
            raise AppError(
                409,
                "STALE_STATE",
                "Session version mismatch",
                session_version=session.session_version,
            )
        plan = json.loads(task.plan_json) if task.plan_json else None
        if plan and plan.get("validation_status") == "stale_supply":
            # Invalidation advances the task version too. Report the actionable
            # supply failure before that stale version; no write bypasses the
            # version check or the later atomic claim.
            raise AppError(409, "STALE_SUPPLY", "Supply context changed, refresh required")
        if expected_state_version != task.state_version:
            raise AppError(
                409,
                "STALE_STATE",
                "State version mismatch",
                task_id=task_id,
                state_version=task.state_version,
            )
        if effective_status(task) != "active" or task.current_step != "awaiting_confirmation":
            raise AppError(409, "TASK_NOT_WRITABLE", "Task not editable")

        if not plan:
            raise AppError(409, "STALE_PLAN", "No plan to add from", task_id=task_id)
        self._assert_cart_store_matches()
        expires_at = plan.get("expires_at")
        if expires_at:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > parsed:
                raise AppError(409, "PLAN_EXPIRED", "Plan expired", task_id=task_id)

        row = next(
            (item for item in plan.get("items") or [] if str(item.get("sku_id")) == sku_id),
            None,
        )
        if row is None:
            raise AppError(422, "INVALID_INPUT", f"SKU {sku_id} not in plan")
        remaining = int(row.get("quantity") or 1) - int(row.get("added_quantity") or 0)
        if quantity < 1 or quantity > remaining:
            raise AppError(
                422,
                "INVALID_INPUT",
                f"Quantity must be between 1 and the outstanding {remaining}",
            )

        offer = self.cart.offers.get_offer(sku_id)
        if not offer or not offer.sellable:
            raise AppError(422, "PRODUCT_UNAVAILABLE", f"SKU {sku_id} unavailable")
        if offer.price_fen != int(row.get("unit_price_fen") or 0):
            raise AppError(409, "PRICE_CHANGED", "Price changed, refresh the plan first")
        if not DeliveryService(self.db).check_delivery(self.store_id, self.delivery_zone_id):
            raise AppError(422, "CONSTRAINT_UNSATISFIED", "Delivery not reachable")
        self._assert_within_budget(plan, row, quantity, task.requirements_json)

        task = self._claim_task(task_id, expected_state_version)
        operation_id = f"op-{uuid4().hex[:12]}"
        op = CartOperation(
            operation_id=operation_id,
            owner_id=self.owner_id,
            idempotency_key=request_id,
            request_digest=digest,
            status="pending",
            task_id=task_id,
        )
        self.db.add(op)
        self.db.flush()

        try:
            applied = self.cart.apply_confirm_items([{"sku_id": sku_id, "quantity": quantity}])
            row["added_quantity"] = int(row.get("added_quantity") or 0) + quantity
            row["remaining_quantity"] = max(0, int(row["quantity"]) - row["added_quantity"])
            # An explicit per-row click is also an explicit selection of that row.
            row["selected"] = True
            plan["plan_version"] = int(plan.get("plan_version") or 1) + 1
            plan = self._recompute(plan)
            task.plan_json = json.dumps(plan)
            # The claim moved the task into ``adding_to_cart``; releasing it is
            # what lets a revision, a confirm or the next turn write again.
            task.current_step = "awaiting_confirmation"
            task.status = "active"
            task.state_version += 1
            task.updated_at = datetime.now(timezone.utc)
            session.session_version += 1
            self.conversation.save_plan_snapshot(
                session.session_id, task_id, plan,
                {"store_id": self.store_id, "delivery_zone_id": self.delivery_zone_id},
            )
            self.conversation.save_message(
                session.session_id,
                task_id=task_id,
                role="assistant",
                kind="action_result",
                content=(
                    f"已单独加入购物车：{quantity} × {row.get('name') or sku_id}"
                    f"（购物车版本 {applied['cart_version']}）"
                ),
                request_id=request_id,
                plan_id=plan.get("plan_id"),
                plan_version=plan.get("plan_version"),
            )

            result = {
                "operation_id": operation_id,
                "task_id": task_id,
                "added_sku_id": sku_id,
                "plan_id": plan.get("plan_id"),
                "plan_version": plan.get("plan_version"),
                "state_version": task.state_version,
                "session_version": session.session_version,
                "cart_version": applied["cart_version"],
                "items_added": applied["items_added"],
                "items": plan.get("items") or [],
                "can_confirm": plan.get("can_confirm", False),
                "outstanding_total_fen": plan.get("outstanding_total_fen", 0),
                "coverage_mode": plan.get("coverage_mode"),
                "coverage_intent": plan.get("coverage_intent"),
                "uncovered_items": plan.get("uncovered_items") or [],
                "gaps": plan.get("gaps") or [],
            }
            op.status = "completed"
            op.result_json = json.dumps(result)
            guide_op = self.operations.find(OP_TYPE, task_id, request_id)
            if guide_op:
                self.operations.complete(guide_op, result)
            self.db.commit()
            return result
        except AppError:
            self.db.rollback()
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a retryable 500
            self.db.rollback()
            raise AppError(500, "INTERNAL_ERROR", str(exc), retryable=True) from exc

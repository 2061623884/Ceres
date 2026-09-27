"""Plan revision: quantity, selection, coverage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services.cart_service import CartService
from app.services.conversation_service import ConversationService
from app.services.offer_service import OfferService
from app.services.operation_service import OperationService
from app.services import plan_contract as contract
from app.services.session_actions import effective_status

SYSTEM_MAX_QTY = 99


class PlanRevisionService:
    def __init__(self, db: Session, owner_id: str, store_id: str, delivery_zone_id: str):
        self.db = db
        self.owner_id = owner_id
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.cart = CartService(db, owner_id, store_id)
        self.offers = OfferService(db, store_id)
        self.conversation = ConversationService(db, owner_id)
        self.operations = OperationService(db, owner_id)

    def _cart_qty(self, sku_id: str) -> int:
        cart = self.cart.get_cart()
        for item in cart.get("items", []):
            if item["sku_id"] == sku_id:
                return item["quantity"]
        return 0

    def _enrich_item(
        self,
        row: dict[str, Any],
        selected: bool,
        quantity: int,
        *,
        quantity_source: str | None = None,
    ) -> dict[str, Any]:
        offer = self.offers.get_offer(row["sku_id"])
        cart_qty = self._cart_qty(row["sku_id"])
        available = int(getattr(offer, "available_qty", 0) or 0) if offer else 0
        added = int(row.get("added_quantity") or 0)
        max_addable = max(0, min(SYSTEM_MAX_QTY, available - cart_qty))
        unit_price = offer.price_fen if offer else 0
        line_total = unit_price * quantity if selected else 0
        source = quantity_source or row.get("quantity_source") or "recommended"
        # The requirement's own pack count is the authority for the shortfall —
        # the shopper's number is what may have changed, so a stale
        # availability/shortfall from the previous version is recomputed here
        # (raising the quantity back to what was wanted clears the gap; lowering
        # it below the wanted count keeps one).
        wanted = int(row.get("recommended_quantity") or quantity)
        shortfall = max(0, wanted - quantity)
        availability = "insufficient_stock" if shortfall > 0 else "available"
        evidence = dict(row.get("evidence") or {})
        if offer is not None:
            # The offer was re-read for this revision, so the evidence stamp is a
            # fresh one instead of the price/stock snapshot of an older version.
            evidence["quoted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            evidence["stock_verified"] = bool(getattr(offer, "sellable", False))
        return {
            **row,
            "selected": selected,
            "quantity": quantity,
            "unit_price_fen": unit_price,
            "line_total_fen": line_total,
            "max_addable_quantity": max_addable,
            "recommended_quantity": row.get("recommended_quantity", quantity),
            "quantity_source": source,
            # Only an explicit edit stores a user quantity; the data-backed
            # recommendation stays available for explanation and for later merges.
            "user_quantity": quantity if source == "user" else row.get("user_quantity"),
            "spec_quantity": row.get("spec_quantity"),
            "spec_unit": row.get("spec_unit"),
            "sell_unit": row.get("sell_unit", "件"),
            "image_kind": row.get("image_kind"),
            # An edit must not resurrect stock that an earlier per-row add used.
            "added_quantity": added,
            "remaining_quantity": max(0, quantity - added),
            "availability": availability,
            "shortfall_quantity": shortfall,
            "evidence": evidence or None,
        }

    def revise(
        self,
        task_id: str,
        *,
        request_id: str,
        expected_session_version: int,
        expected_state_version: int,
        base_plan_id: str,
        base_plan_version: int,
        client_edit_sequence: int,
        items: list[dict[str, Any]],
        coverage_intent: str = "full",
        user_supplied_ingredients: list[str] | None = None,
    ) -> dict[str, Any]:
        task = self.db.get(GuideTask, task_id)
        if not task or task.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        session = self.db.get(GuideSession, task.session_id)
        if not session or session.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

        digest = json.dumps(
            {
                "items": items,
                "coverage": coverage_intent,
                "base_plan_id": base_plan_id,
                "base_plan_version": base_plan_version,
                "expected_session_version": expected_session_version,
                "expected_state_version": expected_state_version,
                "client_edit_sequence": client_edit_sequence,
            },
            sort_keys=True,
        )
        cached = self.operations.check_or_begin(
            "plan_revision", "task", task_id, request_id, digest, "CONFIRM_IN_PROGRESS"
        )
        if cached and cached.result_json:
            return json.loads(cached.result_json)

        if session.current_task_id != task_id:
            raise AppError(409, "STALE_STATE", "Not current task", task_id=task_id)
        if expected_session_version != session.session_version:
            raise AppError(
                409,
                "STALE_STATE",
                "Session version mismatch",
                session_version=session.session_version,
                current_task_id=session.current_task_id,
                state_version=task.state_version,
            )
        if expected_state_version != task.state_version:
            raise AppError(
                409,
                "STALE_STATE",
                "State version mismatch",
                task_id=task_id,
                state_version=task.state_version,
            )
        if effective_status(task) != "active" or task.current_step != "awaiting_confirmation":
            raise AppError(409, "TASK_NOT_WRITABLE", "Task not revisable")

        plan = json.loads(task.plan_json) if task.plan_json else None
        if not plan or plan["plan_id"] != base_plan_id or plan["plan_version"] != base_plan_version:
            raise AppError(409, "STALE_PLAN", "Plan version mismatch", task_id=task_id)

        plan_items = {i["sku_id"]: i for i in plan.get("items", [])}
        plan_mode = plan.get("mode", "bundle")
        seen: set[str] = set()
        enriched: list[dict[str, Any]] = []
        selected_total = 0
        user_supplied = set(user_supplied_ingredients or [])
        req = json.loads(task.requirements_json or "{}")

        for edit in items:
            sku = edit.get("sku_id")
            if not sku or sku in seen:
                raise AppError(422, "INVALID_INPUT", "Duplicate or missing SKU")
            seen.add(sku)
            if sku not in plan_items:
                raise AppError(422, "INVALID_INPUT", f"Unknown SKU {sku}")
            qty = edit.get("quantity")
            if not isinstance(qty, int) or qty < 1 or qty > SYSTEM_MAX_QTY:
                raise AppError(422, "INVALID_INPUT", f"Invalid quantity for {sku}")
            selected = bool(edit.get("selected", True))
            base = plan_items[sku]
            # A quantity the shopper typed is their decision, and is recorded as
            # such so a later incremental target cannot silently overwrite it.
            edited_by_user = qty != int(base.get("quantity") or 1)
            row = self._enrich_item(
                base,
                selected,
                qty,
                quantity_source="user"
                if edited_by_user
                else base.get("quantity_source") or "recommended",
            )
            if selected and qty > row["max_addable_quantity"] + int(
                base.get("added_quantity") or 0
            ):
                # ``max_addable_quantity`` is the headroom *left* after this
                # owner's cart, which already holds the units added by an explicit
                # click. Compare the outstanding part of the edit, not the total.
                raise AppError(422, "INVALID_INPUT", f"Quantity exceeds max for {sku}")
            if selected:
                selected_total += row["line_total_fen"]
            enriched.append(row)

        if len(seen) != len(plan_items):
            raise AppError(422, "INVALID_INPUT", "Must include all plan items")

        # The gaps of this plan version: row-derived supply gaps first, then the
        # row-less ones (an unresolved ingredient cannot be re-derived from a row).
        gaps = contract.collect_gaps(plan.get("gaps"), enriched)
        coverage = contract.coverage(
            enriched,
            gaps,
            coverage_intent,
            user_supplied_ingredients=user_supplied,
            ignore_unselected_required=plan_mode == "alternatives",
        )
        coverage_mode = coverage["coverage_mode"]
        uncovered = coverage["uncovered_items"]

        budget_fen = req.get("budget_fen")
        budget_ok = budget_fen is None or selected_total <= budget_fen
        if plan_mode == "alternatives" and budget_fen is not None:
            selected_lines = [i["line_total_fen"] for i in enriched if i["selected"]]
            budget_ok = bool(selected_lines) and selected_lines[0] <= budget_fen
        can_confirm = coverage["can_confirm"] and budget_ok
        if coverage_intent == "user_supplied" and not user_supplied:
            can_confirm = False

        # The dock remains visible across revisions: never retain the previous
        # plan's outstanding amount after quantities/selection have changed.
        outstanding_total = sum(
            int(row.get("remaining_quantity", row["quantity"])) * row["unit_price_fen"]
            for row in enriched if row["selected"]
        )
        new_version = plan["plan_version"] + 1
        new_plan = {
            **plan,
            "plan_version": new_version,
            "items": enriched,
            "outstanding_total_fen": outstanding_total,
            "selected_total_fen": selected_total,
            "total_price_fen": selected_total,
            "coverage_mode": coverage_mode,
            "coverage_intent": coverage["coverage_intent"],
            "uncovered_items": uncovered,
            "gaps": gaps,
            "can_confirm": can_confirm,
            "client_edit_sequence": client_edit_sequence,
            "expires_at": plan["expires_at"],
        }

        task.plan_json = json.dumps(new_plan)
        task.state_version += 1
        session.session_version += 1
        self.conversation.save_plan_snapshot(task.session_id, task_id, new_plan)

        result = {
            "plan_id": new_plan["plan_id"],
            "plan_version": new_version,
            "state_version": task.state_version,
            "session_version": session.session_version,
            "items": enriched,
            "outstanding_total_fen": outstanding_total,
            "selected_total_fen": selected_total,
            "total_price_fen": selected_total,
            "uncovered_items": uncovered,
            "coverage_mode": coverage_mode,
            "coverage_intent": coverage["coverage_intent"],
            "gaps": gaps,
            "can_confirm": can_confirm,
            "validation_errors": [],
        }
        op = self.operations.find("plan_revision", task_id, request_id)
        if op:
            self.operations.complete(op, result)
        self.db.commit()
        return result

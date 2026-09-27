"""Refresh expired or stale plans with current pricing."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services import plan_contract as contract
from app.services.conversation_service import ConversationService
from app.services.offer_service import OfferService
from app.services.operation_service import OperationService
from app.services.plan_validator import PlanValidator
from app.services.session_actions import effective_status


class PlanRefreshService:
    def __init__(self, db: Session, owner_id: str, store_id: str, delivery_zone_id: str):
        self.db = db
        self.owner_id = owner_id
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.offers = OfferService(db, store_id)
        self.validator = PlanValidator(db, store_id, delivery_zone_id)
        self.conversation = ConversationService(db, owner_id)
        self.operations = OperationService(db, owner_id)

    #: Row fields only the server owns: the client never sends them and a refresh
    #: must never invent or drop them. Facts that the fresh re-check re-reads
    #: (availability, evidence/quoted_at, shortfall) are deliberately *not* here:
    #: carrying a stale supply fact over a new one is exactly the drift this
    #: exists to prevent.
    LEDGER_ROW_KEYS = (
        "added_quantity",
        "group_id",
        "target_kind",
        "target_id",
        "contributions",
        "quantity_source",
        "user_quantity",
        "component_name",
        # P0 requirement identity/evidence: a re-price is not a new requirement.
        "required_item_id",
        "requirement",
    )

    def _carry_purchase_ledger(
        self,
        new_plan: dict[str, Any],
        base_plan: dict[str, Any],
        base_rows: dict[str, dict[str, Any]],
    ) -> None:
        for row in new_plan.get("items") or []:
            base = base_rows.get(str(row.get("sku_id")))
            if not base:
                continue
            for key in self.LEDGER_ROW_KEYS:
                if key in base:
                    row[key] = base[key]
            added = int(base.get("added_quantity") or 0)
            row["added_quantity"] = added
            row["remaining_quantity"] = max(0, int(row.get("quantity") or 1) - added)
            if base.get("recommended_quantity"):
                row["recommended_quantity"] = base["recommended_quantity"]

        new_plan["targets"] = base_plan.get("targets", [])
        new_plan["merged_sku_contributions"] = base_plan.get("merged_sku_contributions", [])
        outstanding = sum(
            int(row.get("unit_price_fen") or 0) * int(row.get("remaining_quantity") or 0)
            for row in new_plan.get("items") or []
            if row.get("selected", True)
        )
        new_plan["outstanding_total_fen"] = outstanding
        if outstanding == 0:
            # Nothing left to buy: a refresh must not re-arm a spent plan.
            new_plan["can_confirm"] = False

    def refresh(
        self,
        task_id: str,
        *,
        request_id: str,
        expected_session_version: int,
        expected_state_version: int,
        base_plan_id: str,
        base_plan_version: int,
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task = self.db.get(GuideTask, task_id)
        if not task or task.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        session = self.db.get(GuideSession, task.session_id)
        if not session:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

        digest = json.dumps(
            {
                "base_plan_id": base_plan_id,
                "base_plan_version": base_plan_version,
                "expected_session_version": expected_session_version,
                "expected_state_version": expected_state_version,
                "items": items,
            },
            sort_keys=True,
        )
        cached = self.operations.check_or_begin(
            "plan_refresh", "task", task_id, request_id, digest, "CONFIRM_IN_PROGRESS"
        )
        if cached and cached.result_json:
            return json.loads(cached.result_json)

        if session.current_task_id != task_id:
            raise AppError(409, "STALE_STATE", "Not current task", task_id=task_id)
        if expected_session_version != session.session_version:
            raise AppError(409, "STALE_STATE", "Session version mismatch", session_version=session.session_version)
        if expected_state_version != task.state_version:
            raise AppError(409, "STALE_STATE", "State version mismatch", state_version=task.state_version)
        if effective_status(task) != "active" or task.current_step != "awaiting_confirmation":
            raise AppError(409, "TASK_NOT_WRITABLE", "Task not refreshable")

        plan = json.loads(task.plan_json) if task.plan_json else None
        if not plan or plan["plan_id"] != base_plan_id or plan["plan_version"] != base_plan_version:
            raise AppError(409, "STALE_PLAN", "Plan version mismatch", task_id=task_id)

        base_rows = {
            str(item.get("sku_id")): item for item in plan.get("items") or []
        }
        if items:
            # A caller-supplied edit keeps the base row's server-owned authority
            # (a hand-typed quantity must not be silently rescaled to a
            # recommendation it never asked for).
            edit_items = [
                {**base_rows.get(str(edit.get("sku_id")), {}), **edit}
                for edit in items
            ]
        else:
            # Ditto for the stored rows themselves: pass the whole row so the
            # re-check sees ``quantity_source``/``requirement`` as they really are.
            edit_items = [dict(item) for item in plan.get("items") or []]
        candidate_ids = [i["sku_id"] for i in plan.get("items", [])]
        req = json.loads(task.requirements_json or "{}")
        checked = self.validator.check_constraints(
            edit_items,
            candidate_ids,
            budget_fen=req.get("budget_fen"),
            mode=plan.get("mode", "bundle"),
            # The persisted intent, not the coverage *result*: mapping "partial"
            # onto the intent vocab silently downgraded partial plans.
            coverage_intent=contract.normalize_intent(plan.get("coverage_intent")),
            user_supplied_ingredients=plan.get("user_supplied_ingredients", []),
        )
        stale_items: list[dict[str, Any]] = []
        for row in checked["items"]:
            added = int((base_rows.get(str(row["sku_id"])) or {}).get("added_quantity") or 0)
            outstanding = max(0, int(row["quantity"]) - added)
            offer = self.offers.get_offer(row["sku_id"])
            if not offer or not offer.sellable:
                stale_items.append({"sku_id": row["sku_id"], "reason": "not_sellable"})
            elif offer.available_qty < outstanding:
                stale_items.append({"sku_id": row["sku_id"], "reason": "insufficient_stock"})
        checked_skus = {str(row["sku_id"]) for row in checked["items"]}
        gap_by_sku = {
            str(gap.get("sku_id")): str(gap.get("kind"))
            for gap in checked.get("gaps") or []
            if isinstance(gap, dict) and gap.get("sku_id")
        }
        for sku_id in base_rows:
            if sku_id in checked_skus:
                continue
            # The re-check dropped this row entirely: the store can no longer
            # supply it, which is a supply change like any other.
            stale_items.append({"sku_id": sku_id, "reason": gap_by_sku.get(sku_id, "not_sellable")})

        new_version = plan["plan_version"] + 1
        supply_ctx = {
            "store_id": self.store_id,
            "delivery_zone_id": self.delivery_zone_id,
            "supply_version": session.session_version,
        }
        new_plan = self.validator.publish_snapshot(
            checked,
            plan_id=plan["plan_id"],
            plan_version=new_version,
            mode=plan.get("mode", "bundle"),
            supply_context=supply_ctx,
        )
        # A re-price is not a new purchase: the server-owned accounting (what was
        # already added, which target contributed it, the shopper's own quantity)
        # has to survive the refresh, or the next confirmation buys it again.
        self._carry_purchase_ledger(new_plan, plan, base_rows)
        # Re-derive one consistent gap/coverage block: the row-less gaps of the
        # version being refreshed (an unresolved ingredient has no row to re-check)
        # plus whatever this re-check just found.
        coverage_intent = contract.normalize_intent(
            new_plan.get("coverage_intent") or plan.get("coverage_intent")
        )
        new_plan["coverage_intent"] = coverage_intent
        new_plan["gaps"] = contract.collect_gaps(
            [*(plan.get("gaps") or []), *(checked.get("gaps") or [])],
            new_plan.get("items") or [],
        )
        coverage = contract.coverage(
            new_plan.get("items") or [],
            new_plan["gaps"],
            coverage_intent,
            user_supplied_ingredients=plan.get("user_supplied_ingredients", []),
        )
        new_plan["coverage_mode"] = coverage["coverage_mode"]
        new_plan["uncovered_items"] = coverage["uncovered_items"]
        new_plan["can_confirm"] = coverage["can_confirm"]
        if int(new_plan.get("outstanding_total_fen") or 0) == 0:
            # Nothing left to buy: a refresh must not re-arm a spent plan.
            new_plan["can_confirm"] = False
        new_plan["stale_items"] = stale_items
        if stale_items:
            new_plan["can_confirm"] = False
            new_plan["validation_status"] = "stale_supply" if plan.get("validation_status") == "stale_supply" else checked["validation_status"]

        task.plan_json = json.dumps(new_plan)
        task.state_version += 1
        session.session_version += 1
        self.conversation.save_plan_snapshot(task.session_id, task_id, new_plan, supply_ctx)

        result = {
            **new_plan,
            "plan_id": new_plan["plan_id"],
            "plan_version": new_version,
            "state_version": task.state_version,
            "session_version": session.session_version,
            "items": new_plan["items"],
            "selected_total_fen": new_plan["selected_total_fen"],
            "total_price_fen": new_plan["total_price_fen"],
            "can_confirm": new_plan["can_confirm"],
            "stale_items": stale_items,
            "coverage_mode": new_plan.get("coverage_mode", "full"),
            "coverage_intent": new_plan.get("coverage_intent"),
            "uncovered_items": new_plan.get("uncovered_items", []),
            "gaps": new_plan.get("gaps", []),
        }
        op = self.operations.find("plan_refresh", task_id, request_id)
        if op:
            self.operations.complete(op, result)
        self.db.commit()
        return result

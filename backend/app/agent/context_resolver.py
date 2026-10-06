"""Resolve session/task context for turn interpretation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agent.clarification_state import PendingClarification
from app.agent.state import TaskState
from app.models.session import GuideSession, GuideTask
from app.services.conversation_service import ConversationService
from app.services.session_actions import effective_status


@dataclass
class ResolvedContext:
    session: GuideSession
    task: GuideTask | None
    state: TaskState | None
    entry: dict[str, Any]
    store_id: str
    delivery_zone_id: str
    task_finished: bool
    has_editable_plan: bool
    requirements: dict[str, Any]
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    pending_clarification: PendingClarification | None = None
    purchase_summary: dict[str, Any] | None = None
    intent: str | None = None
    # Navigation is advisory context, not the trusted store/delivery scope.
    view: dict[str, Any] = field(default_factory=dict)


class ContextResolver:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def resolve(self, session_id: str, *, message_limit: int = 10) -> ResolvedContext:
        session = self.db.get(GuideSession, session_id)
        if not session or session.owner_id != self.owner_id:
            raise PermissionError("SESSION_FORBIDDEN")
        entry = json.loads(session.entry_context_json)
        try:
            saved_view = json.loads(session.view_context_json or "{}")
        except (TypeError, ValueError):
            saved_view = {}
        view = {
            key: saved_view[key]
            for key in ("page", "category_id", "product_id", "activity_id")
            if isinstance(saved_view, dict) and key in saved_view
        }
        store_id = entry.get("store_id", "store-demo-01")
        delivery_zone_id = entry.get("delivery_zone_id", "zone-default")
        task = None
        state = None
        if session.current_task_id:
            task = self.db.get(GuideTask, session.current_task_id)
            if task and task.owner_id == self.owner_id:
                state = TaskState.from_db(task, entry)
        task_finished = bool(
            task and effective_status(task) in ("completed", "cancelled", "superseded")
        )
        has_editable_plan = bool(
            task
            and task.current_step == "awaiting_confirmation"
            and task.plan_json
            and effective_status(task) == "active"
        )
        requirements = json.loads(task.requirements_json or "{}") if task else {}

        conv = ConversationService(self.db, self.owner_id)
        recent = conv.list_messages(session_id, limit=message_limit)
        recent_messages = recent.get("messages", [])

        pending = None
        if task and task.pending_clarification_json:
            pending = PendingClarification.from_json(task.pending_clarification_json)

        purchase_summary = self._build_purchase_summary(task, state)
        intent = task.intent if task else (
            "category_selection" if entry.get("page") == "category" else None
        )

        return ResolvedContext(
            session=session,
            task=task,
            state=state,
            entry=entry,
            store_id=store_id,
            delivery_zone_id=delivery_zone_id,
            task_finished=task_finished,
            has_editable_plan=has_editable_plan,
            requirements=requirements,
            recent_messages=recent_messages,
            pending_clarification=pending,
            purchase_summary=purchase_summary,
            intent=intent,
            view=view,
        )

    def _build_purchase_summary(
        self,
        task: GuideTask | None,
        state: TaskState | None,
    ) -> dict[str, Any] | None:
        if not task:
            return None
        summary: dict[str, Any] = {
            "task_id": task.task_id,
            "status": effective_status(task),
            "goal": None,
            # ``items`` are the items the *confirmation actually added*, not the
            # plan rows: the plan may have changed after the cart write.
            "items": [],
            # ``None`` means "we do not know the amount", never "it was free".
            "total_fen": None,
            "confirmed": bool(task.user_confirmed),
            "source": None,
        }
        if state:
            summary["goal"] = state.requirements.goal

        plan_items = self._plan_items_by_sku(task)
        if task.cart_result_json:
            cart = json.loads(task.cart_result_json)
            added = cart.get("items_added") or []
            summary["source"] = "cart_result"
            summary["items"] = [
                self._enrich_item(item, plan_items) for item in added if item.get("sku_id")
            ]
            summary["total_fen"] = self._total_from_items(cart, summary["items"])
            summary["cart_version"] = cart.get("cart_version")
            return summary

        if task.plan_json and task.user_confirmed:
            plan = json.loads(task.plan_json)
            selected = [i for i in plan.get("items", []) if i.get("selected", True)]
            summary["source"] = "plan"
            summary["items"] = [
                {
                    "sku_id": i.get("sku_id"),
                    "name": i.get("name"),
                    "quantity": i.get("quantity"),
                    "unit_price_fen": i.get("unit_price_fen"),
                    "line_total_fen": i.get("line_total_fen"),
                }
                for i in selected
                if i.get("sku_id")
            ]
            total = plan.get("selected_total_fen")
            if total is None:
                total = self._sum_known_line_totals(summary["items"])
            summary["total_fen"] = total
            return summary
        return None

    @staticmethod
    def _plan_items_by_sku(task: GuideTask) -> dict[str, dict[str, Any]]:
        if not task.plan_json:
            return {}
        try:
            plan = json.loads(task.plan_json)
        except ValueError:
            return {}
        return {
            str(item["sku_id"]): item
            for item in plan.get("items", [])
            if item.get("sku_id")
        }

    @staticmethod
    def _enrich_item(
        added: dict[str, Any],
        plan_items: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """The cart only records sku_id + quantity; names/prices come from the plan."""
        sku_id = str(added["sku_id"])
        plan_item = plan_items.get(sku_id) or {}
        quantity = added.get("quantity")
        unit_price = added.get("unit_price_fen", plan_item.get("unit_price_fen"))
        line_total = added.get("line_total_fen", plan_item.get("line_total_fen"))
        if line_total is None and unit_price is not None and quantity is not None:
            line_total = unit_price * quantity
        return {
            "sku_id": sku_id,
            "name": added.get("name") or plan_item.get("name"),
            "quantity": quantity,
            "unit_price_fen": unit_price,
            "line_total_fen": line_total,
        }

    @staticmethod
    def _sum_known_line_totals(items: list[dict[str, Any]]) -> int | None:
        totals = [item.get("line_total_fen") for item in items]
        if not items or any(total is None for total in totals):
            return None
        return sum(int(total) for total in totals)

    @classmethod
    def _total_from_items(
        cls,
        cart: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> int | None:
        if cart.get("total_fen") is not None:
            return int(cart["total_fen"])
        return cls._sum_known_line_totals(items)

"""Commit a validated plan result onto a task.

This is the one place a plan write happens. It owns:

* merging the new target into the plan already on screen (through
  ``ShoppingPlanService`` — no pricing, packing or stock rule is re-implemented
  here);
* recording the constraints the *user* stated (a recipe default never becomes a
  stored user fact);
* opening a fresh task when the current one is settled, so confirmed history
  stays immutable;
* committing before anybody can act on the plan, because plan ids, task id and
  versions must exist before ``plan.ready`` or the HTTP response exposes them.

It is not a workflow: it does not route turns, call a model, or decide policy.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agent.state import Requirements, TaskState
from app.models.session import GuideSession, GuideTask

from app.services.cart_service import CartService
from app.services.validation_context import ValidationContext
from app.services.shopping_plan_service import ShoppingPlanService, group_id_for
from app.services.task_lifecycle_service import TaskLifecycleService
from app.services.template_matcher import dish_display_name, get_template_by_id


def plan_goal(plan: dict[str, Any]) -> str | None:
    """The plan's own description: the distinct target names it really contains."""
    names = [str(t.get("name")) for t in plan.get("targets") or [] if t.get("name")]
    return " + ".join(dict.fromkeys(names)) if names else None


class PlanCommitService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
        self.tasks = TaskLifecycleService(db, owner_id)

    def apply_result(
        self,
        session: GuideSession,
        state: TaskState | None,
        plan_result: dict[str, Any],
        args: dict[str, Any],
        *,
        store_id: str,
        delivery_zone_id: str,
        anchor: Any = None,
        before_persist: Callable[[], None] | None = None,
        opens_new_task: bool = False,
    ) -> TaskState:
        """Persist a validated plan inside the caller's transaction.

        ``operation`` decides how the new target relates to what is on screen:
        ``replace`` (user said 换成), ``append`` (还要/再来) and ``resize`` (人数变化)
        both upsert only the target's group, so previously ticked rows and
        hand-edited quantities survive untouched.

        ``opens_new_task`` is the caller's validated switch decision: a replace
        is a *new* goal, so it opens its own task and supersedes the one it
        replaces. That is what makes the old plan unmistakably not editable.

        ``before_persist`` is the caller's last refusal point: it runs after the
        plan has been merged — a merge can be slow — and immediately before the
        write. A caller that raises there commits nothing; a new task opened above
        is rolled back with the rest of the abandoned transaction.

        The Graph commit node owns the surrounding transaction; this method only
        flushes so the receipt can pin the very same rows before the coordinator
        commits the business effect, receipt and conversation tail together.
        """
        # Refuse a snapshot the live session has outgrown: the model call takes
        # real time, and the shopper may have edited, confirmed or replaced the
        # task since. For a taskless turn this also stops an old snapshot from
        # opening a task over one another request already created.
        self.tasks.assert_turn_anchor(anchor)

        terminal = state is None or self.tasks.task_is_terminal(state.task_id)
        fresh_goal = bool(opens_new_task) or terminal
        if fresh_goal:
            terminal = True
        base_plan = None if terminal else (state.plan or None)

        target_kind = str(plan_result.get("target_kind") or args.get("target_kind") or "dish")
        target_id = str(
            plan_result.get("target_id") or args.get("target_id") or args.get("dish_id") or ""
        )
        goal = None
        if target_kind == "dish" and target_id:
            dish = get_template_by_id(self.db, str(target_id))
            if dish:
                goal = dish_display_name(dish)

        group_id = str(plan_result.get("group_id") or group_id_for(target_kind, target_id))
        operation = str(args.get("operation") or plan_result.get("operation") or "append")
        if base_plan is None:
            # Nothing to preserve: the first plan of a task is always a replace.
            operation = "replace"


        shopping = ShoppingPlanService(self.db, store_id, delivery_zone_id)
        merged = shopping.merge_plan(
            base_plan,
            plan_result,
            group_id=group_id,
            operation=operation,
            # Stock headroom must account for this owner's cart across the *whole*
            # merged plan, not just the rows the new target brought along.
            cart_quantities=CartService(self.db, self.owner_id, store_id).quantities_for(None),
            ctx=ValidationContext.from_requirements(
                Requirements(specification=args["specification"],
                             excluded_ingredients=args.get("exclude_ingredients", [])),
                store_id=store_id, delivery_zone_id=delivery_zone_id,
            ),
        )
        # Build first; a failed/stale/stopped build must not supersede anything.
        if before_persist is not None:
            before_persist()
        self.tasks.assert_turn_anchor(anchor)
        target = state
        if terminal:
            target = self.tasks.create_purchase_task(
                session, state,
                {**args, "target_kind": target_kind, "target_id": target_id},
                store_id=store_id, delivery_zone_id=delivery_zone_id,
                entry_context=(state.entry_context if state is not None
                               else json.loads(session.entry_context_json)),
                goal=goal, fresh_goal=fresh_goal,
            )
        if target_kind == "dish" and target_id:
            target.active_template_id = target_id
        merged_goal = plan_goal(merged)
        if merged_goal:
            target.requirements.goal = merged_goal
        target_people = (plan_result.get("target") or {}).get("people")
        target_people_source = (plan_result.get("target") or {}).get("people_source")
        if target_people and target_people_source == "user":
            target.requirements.people = int(target_people)
        if args.get("budget_fen") is not None:
            target.requirements.budget_fen = int(args["budget_fen"])
        target.requirements.specification = dict(args["specification"])
        if "selection_goal" in plan_result["target"]:
            selected_constraints = plan_result["target"]["selection_goal"]["constraints"]
            selected_budget = selected_constraints["budget_yuan"]
            target.requirements.budget_fen = (
                round(selected_budget * 100) if selected_budget is not None else None
            )
            target.requirements.excluded_ingredients = list(args.get("exclude_ingredients", []))
            target.requirements.specification = dict(selected_constraints["specification"])
        # A per-target validation only ever sees its own rows, so the merged plan
        # can exceed the budget the task already carries. The confirmation path
        # rejects that, but ``can_confirm`` must not promise a write that will be
        # refused: gate the merged result against the persisted budget here.
        budget_fen = target.requirements.budget_fen
        if budget_fen is not None and int(merged.get("selected_total_fen") or 0) > int(
            budget_fen
        ):
            merged["can_confirm"] = False
            merged["budget_exceeded"] = True
        excluded = list(args.get("exclude_ingredients") or [])
        if excluded:
            target.requirements.excluded_ingredients = list(
                dict.fromkeys(target.requirements.excluded_ingredients + excluded)
            )
        target.plan = merged
        target.validation_result = dict(plan_result)
        target.candidate_products = [
            item["sku_id"] for item in merged.get("items", []) if item.get("sku_id")
        ]
        target.current_step = "awaiting_confirmation"
        target.status = "active"
        target.state_version += 1
        target.user_confirmed = False
        target.pending_clarification = None
        # A brand-new task has no prior version to match; an existing one is
        # written conditionally, so a concurrent edit is never overwritten.
        target.to_db(
            self.db,
            expected_version=(
                anchor.state_version if anchor is not None and not terminal
                else (target.state_version - 1 if not terminal else None)
            ),
        )
        task = self.db.get(GuideTask, target.task_id)
        if task:
            task.pending_clarification_json = None
        session.candidate_dishes_json = "[]"
        session.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return target

__all__ = ["PlanCommitService", "plan_goal"]

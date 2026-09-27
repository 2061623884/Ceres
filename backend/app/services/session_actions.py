"""Compute available actions from task/session state."""

from __future__ import annotations

from app.models.session import GuideTask


def effective_status(task: GuideTask | None) -> str | None:
    if not task:
        return None
    if task.status != "active":
        return task.status
    if task.current_step == "completed":
        return "completed"
    return task.status


def available_actions_for_task(task: GuideTask | None) -> list[str]:
    if not task:
        return ["send_message"]
    eff = effective_status(task)
    step = task.current_step
    if eff in ("completed", "cancelled", "superseded"):
        return ["start_new", "send_message"]
    if step == "adding_to_cart":
        return []
    if step == "awaiting_confirmation":
        actions = ["confirm", "cancel", "modify", "send_message"]
        plan = task.plan_json
        if plan and '"validation_status":"stale_supply"' in plan.replace(" ", ""):
            actions = [a for a in actions if a != "confirm"]
            if "refresh_plan" not in actions:
                actions.append("refresh_plan")
        return actions
    if step == "degraded":
        return ["cancel", "send_message"]
    return ["cancel", "send_message"]

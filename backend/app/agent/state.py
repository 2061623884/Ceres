"""Task state types and persistence helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.session import GuideTask


@dataclass
class Requirements:
    goal: str | None = None
    people: int | None = None
    budget_fen: int | None = None
    quantity: int | None = None
    category_id: str | None = None
    usage: str | None = None
    specification: dict[str, Any] = field(default_factory=dict)
    preferences: list[str] = field(default_factory=list)
    excluded_ingredients: list[str] = field(default_factory=list)
    pantry_confirmed: list[str] = field(default_factory=list)
    complexity: str | None = None
    delivery_deadline: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "people": self.people,
            "budget_fen": self.budget_fen,
            "quantity": self.quantity,
            "category_id": self.category_id,
            "usage": self.usage,
            "specification": self.specification,
            "preferences": self.preferences,
            "excluded_ingredients": self.excluded_ingredients,
            "pantry_confirmed": self.pantry_confirmed,
            "complexity": self.complexity,
            "delivery_deadline": self.delivery_deadline,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Requirements:
        return cls(
            goal=data.get("goal"),
            people=data.get("people"),
            budget_fen=data.get("budget_fen"),
            quantity=data.get("quantity"),
            category_id=data.get("category_id"),
            usage=data.get("usage"),
            specification=data.get("specification") or {},
            preferences=data.get("preferences") or [],
            excluded_ingredients=data.get("excluded_ingredients") or [],
            pantry_confirmed=data.get("pantry_confirmed") or [],
            complexity=data.get("complexity"),
            delivery_deadline=data.get("delivery_deadline"),
        )


@dataclass
class TaskState:
    session_id: str
    task_id: str
    owner_id: str
    state_version: int
    intent: str
    entry_context: dict[str, Any]
    requirements: Requirements
    requirements_version: int = 1
    missing_constraints: list[str] = field(default_factory=list)
    candidate_set_id: str | None = None
    candidate_products: list[str] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    current_step: str = "understanding"
    user_confirmed: bool = False
    confirmation_id: str | None = None
    cart_result: dict[str, Any] | None = None
    clarification_count: int = 0
    replacement_count: int = 0
    active_template_id: str | None = None
    status: str = "active"
    pending_clarification: dict[str, Any] | None = None
    task_context: dict[str, Any] | None = None
    supply_context: dict[str, Any] | None = None
    terminal_reason: str | None = None

    def to_db(self, db: Session, expected_version: int | None = None) -> GuideTask:
        from sqlalchemy import text

        task = db.get(GuideTask, self.task_id)
        is_new = task is None
        if is_new:
            task = GuideTask(
                task_id=self.task_id,
                session_id=self.session_id,
                owner_id=self.owner_id,
            )
            db.add(task)
        elif expected_version is not None:
            result = db.execute(
                text(
                    "UPDATE guide_tasks SET state_version = :new_ver "
                    "WHERE task_id = :tid AND owner_id = :oid AND state_version = :ver"
                ),
                {
                    "new_ver": self.state_version,
                    "tid": self.task_id,
                    "oid": self.owner_id,
                    "ver": expected_version,
                },
            )
            if result.rowcount != 1:
                from app.core.errors import AppError

                raise AppError(
                    409,
                    "STALE_STATE",
                    "Task version mismatch",
                    task_id=self.task_id,
                    state_version=task.state_version,
                )
        task.state_version = self.state_version
        task.intent = self.intent
        task.current_step = self.current_step
        task.requirements_json = json.dumps(self.requirements.to_dict())
        task.requirements_version = self.requirements_version
        task.missing_constraints_json = json.dumps(self.missing_constraints)
        task.candidate_set_id = self.candidate_set_id
        task.candidate_products_json = json.dumps(self.candidate_products)
        task.plan_json = json.dumps(self.plan) if self.plan else None
        task.validation_result_json = (
            json.dumps(self.validation_result) if self.validation_result else None
        )
        task.clarification_count = self.clarification_count
        task.replacement_count = self.replacement_count
        task.active_template_id = self.active_template_id
        task.user_confirmed = self.user_confirmed
        task.confirmation_id = self.confirmation_id
        task.cart_result_json = json.dumps(self.cart_result) if self.cart_result else None
        task.status = self.status
        task.pending_clarification_json = (
            json.dumps(self.pending_clarification) if self.pending_clarification else None
        )
        task.task_context_json = json.dumps(self.task_context) if self.task_context else None
        task.supply_context_json = json.dumps(self.supply_context) if self.supply_context else None
        task.terminal_reason = self.terminal_reason
        task.updated_at = datetime.now(timezone.utc)
        if is_new:
            db.flush()
        return task

    @classmethod
    def from_db(cls, task: GuideTask, entry_context: dict[str, Any]) -> TaskState:
        return cls(
            session_id=task.session_id,
            task_id=task.task_id,
            owner_id=task.owner_id,
            state_version=task.state_version,
            intent=task.intent,
            entry_context=entry_context,
            requirements=Requirements.from_dict(json.loads(task.requirements_json or "{}")),
            requirements_version=task.requirements_version,
            missing_constraints=json.loads(task.missing_constraints_json or "[]"),
            candidate_set_id=task.candidate_set_id,
            candidate_products=json.loads(task.candidate_products_json or "[]"),
            plan=json.loads(task.plan_json) if task.plan_json else None,
            validation_result=(
                json.loads(task.validation_result_json) if task.validation_result_json else None
            ),
            current_step=task.current_step,
            user_confirmed=task.user_confirmed,
            confirmation_id=task.confirmation_id,
            cart_result=json.loads(task.cart_result_json) if task.cart_result_json else None,
            clarification_count=task.clarification_count,
            replacement_count=task.replacement_count,
            active_template_id=task.active_template_id,
            status=task.status,
            pending_clarification=(
                json.loads(task.pending_clarification_json)
                if task.pending_clarification_json
                else None
            ),
            task_context=json.loads(task.task_context_json) if task.task_context_json else None,
            supply_context=(
                json.loads(task.supply_context_json) if task.supply_context_json else None
            ),
            terminal_reason=task.terminal_reason,
        )


def new_task_id() -> str:
    return f"task-{uuid4().hex[:12]}"

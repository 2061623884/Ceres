"""Task lifecycle: create, supersede, cancel with CAS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.state import Requirements, TaskState, new_task_id
from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services.conversation_service import ConversationService
from app.services.operation_service import OperationService
from app.services.session_actions import effective_status


WRITABLE_STEPS = frozenset(
    {
        "understanding",
        "clarifying",
        "searching",
        "planning",
        "validating",
        "awaiting_confirmation",
        "degraded",
    }
)


@dataclass
class TurnAnchor:
    """The session and task version a turn took its snapshot from.

    A model call takes real time. The shopper can edit the plan, confirm it, or
    start another task while it runs, so a write proposed from that snapshot is
    only allowed if nothing moved. The anchor is per-turn state, never persisted.
    """

    session_id: str
    task_id: str | None
    state_version: int

    def advance(self, state_version: int, task_id: str | None = None) -> None:
        """Move the anchor forward after *this* turn committed its own write.

        A turn may apply several changes in a row; each one is checked against
        what it just wrote, not against what it started from. That includes the
        task: a mutation may legitimately open a new task (a purchase after a
        settled one), and every later mutation of the same turn then belongs to
        *that* task. Only this turn's own committed write may move the anchor —
        anything another request did still fails the check.
        """
        self.state_version = int(state_version)
        if task_id is not None:
            self.task_id = task_id


class TaskLifecycleService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
        self.conversation = ConversationService(db, owner_id)
        self.operations = OperationService(db, owner_id)

    def anchor_turn(self, session: GuideSession, state: TaskState | None) -> TurnAnchor:
        """Capture what this turn is allowed to write against."""
        return TurnAnchor(
            session_id=session.session_id,
            task_id=session.current_task_id,
            state_version=int(getattr(state, "state_version", 0) or 0),
        )

    def assert_turn_anchor(self, anchor: TurnAnchor | None) -> None:
        """Refuse to write from a snapshot the live session has outgrown.

        The live values are read with plain SQL on purpose: the ORM identity map
        can still be holding the copy this turn loaded, so a change committed by
        another connection — the shopper's own edit — would go unnoticed. The
        conditional update in ``TaskState.to_db`` is the atomic backstop; this is
        the typed, early refusal.
        """
        if anchor is None:
            return
        live_session = self.db.execute(
            text(
                "SELECT current_task_id FROM guide_sessions "
                "WHERE session_id = :sid AND owner_id = :oid"
            ),
            {"sid": anchor.session_id, "oid": self.owner_id},
        ).first()
        if live_session is None:
            raise AppError(409, "STALE_STATE", "回合开始时的会话已不存在，本轮改动未执行。")
        if live_session[0] != anchor.task_id:
            # Includes the taskless case: another request opened a task while this
            # turn was thinking, and the old snapshot must not take the session over.
            raise AppError(
                409,
                "STALE_STATE",
                "回合开始后会话的任务已变化，本轮改动未执行。",
                current_task_id=live_session[0],
            )
        if anchor.task_id is None:
            return
        live_task = self.db.execute(
            text(
                "SELECT state_version, status FROM guide_tasks "
                "WHERE task_id = :tid AND owner_id = :oid"
            ),
            {"tid": anchor.task_id, "oid": self.owner_id},
        ).first()
        if live_task is None:
            raise AppError(409, "STALE_STATE", "回合开始时的任务已不存在，本轮改动未执行。")
        if int(live_task[0]) != anchor.state_version:
            raise AppError(
                409,
                "STALE_STATE",
                "清单已被其他操作修改，本轮改动未执行。",
                state_version=int(live_task[0]),
            )

    def task_is_terminal(self, task_id: str | None) -> bool:
        """Whether history is settled: a missing task counts as settled.

        A confirmed, cancelled or superseded task is immutable — editing it in
        place would rewrite what the shopper already bought.
        """
        if not task_id:
            return True
        task = self.db.get(GuideTask, task_id)
        if task is None:
            return True
        return effective_status(task) in ("completed", "cancelled", "superseded")

    def create_purchase_task(
        self,
        session: GuideSession,
        previous: TaskState | None,
        args: dict[str, Any],
        *,
        store_id: str,
        delivery_zone_id: str,
        entry_context: dict[str, Any],
        goal: str | None = None,
        fresh_goal: bool = False,
    ) -> TaskState:
        """Open a fresh purchase task for a plan, superseding an active one.

        The user's own stated constraints carry over; a recipe default never
        becomes a stored user fact. ``goal`` is the recipe's display name when the
        caller resolved one.

        ``fresh_goal`` is set when the caller has already decided this is a
        *different* goal (a validated switch). Then the previous goal's local
        facts — its dish name, its headcount, its budget — are not inherited;
        only the session-level exclusions are, because those were the shopper's
        standing constraints rather than one target's property.
        """
        previous_req = getattr(previous, "requirements", None) or Requirements()
        target_kind = str(args.get("target_kind") or ("dish" if args.get("dish_id") else ""))
        target_id = str(args.get("target_id") or args.get("dish_id") or "")
        dish_id = target_id if target_kind == "dish" else None
        inherited = None if fresh_goal else previous_req
        state = TaskState(
            session_id=session.session_id,
            task_id=new_task_id(),
            owner_id=self.owner_id,
            state_version=1,
            intent="purchase_task",
            entry_context=entry_context,
            requirements=Requirements(
                goal=goal or (inherited.goal if inherited else None),
                people=args.get("people") or (inherited.people if inherited else None),
                budget_fen=(
                    args["budget_fen"]
                    if args.get("budget_fen") is not None
                    else (inherited.budget_fen if inherited else None)
                ),
                excluded_ingredients=list(
                    dict.fromkeys(
                        list(previous_req.excluded_ingredients or [])
                        + list(args.get("exclude_ingredients") or [])
                    )
                ),
                specification=dict((inherited.specification if inherited else None) or {}),
            ),
            current_step="understanding",
            active_template_id=str(dish_id) if dish_id else None,
            task_context=entry_context,
            supply_context={"store_id": store_id, "delivery_zone_id": delivery_zone_id},
        )
        if previous is not None:
            old = self.db.get(GuideTask, previous.task_id)
            if old is not None and effective_status(old) == "active":
                old.status = "superseded"
                old.state_version += 1
                old.terminal_reason = f"superseded_by:{state.task_id}"
                old.updated_at = datetime.now(timezone.utc)
        return self.create_task_from_state(session, state)

    def _cas_task_update(self, task_id: str, expected_version: int, **fields: Any) -> GuideTask:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        params = {**fields, "task_id": task_id, "owner_id": self.owner_id, "version": expected_version}
        result = self.db.execute(
            text(
                f"UPDATE guide_tasks SET {sets}, state_version = state_version + 1, "
                f"updated_at = :updated_at WHERE task_id = :task_id AND owner_id = :owner_id "
                f"AND status = 'active' AND state_version = :version"
            ),
            {**params, "updated_at": datetime.now(timezone.utc)},
        )
        if result.rowcount != 1:
            task = self.db.get(GuideTask, task_id)
            raise AppError(
                409,
                "STALE_STATE",
                "Task version mismatch",
                task_id=task_id,
                state_version=task.state_version if task else expected_version,
            )
        task = self.db.get(GuideTask, task_id)
        if not task:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        return task

    def supersede_current(
        self,
        session: GuideSession,
        old_task: GuideTask,
        reason: str,
    ) -> None:
        if old_task.current_step == "adding_to_cart":
            raise AppError(409, "TASK_NOT_WRITABLE", "Task in confirmation")
        new_id = new_task_id()
        old_task.status = "superseded"
        old_task.terminal_reason = f"superseded_by:{new_id}"
        old_task.state_version += 1
        old_task.updated_at = datetime.now(timezone.utc)
        session.current_task_id = None  # caller sets new task

    def create_task_from_state(
        self,
        session: GuideSession,
        state: TaskState,
        *,
        supersede_old: GuideTask | None = None,
    ) -> TaskState:
        if supersede_old:
            if supersede_old.current_step == "adding_to_cart":
                raise AppError(409, "TASK_NOT_WRITABLE", "Task in confirmation")
            supersede_old.status = "superseded"
            supersede_old.terminal_reason = f"superseded_by:{state.task_id}"
            supersede_old.state_version += 1
            supersede_old.updated_at = datetime.now(timezone.utc)
        state.to_db(self.db, expected_version=None)
        session.current_task_id = state.task_id
        session.session_version += 1
        return state

    def cancel_task(
        self,
        task_id: str,
        *,
        request_id: str,
        expected_session_version: int,
        expected_state_version: int,
        request_digest: str,
    ) -> dict[str, Any]:
        task = self.db.get(GuideTask, task_id)
        if not task or task.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
        session = self.db.get(GuideSession, task.session_id)
        if not session:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

        cached = self.operations.check_or_begin(
            "cancel", "task", task_id, request_id, request_digest
        )
        if cached and cached.result_json:
            return json.loads(cached.result_json)

        if effective_status(task) != "active":
            raise AppError(409, "TASK_NOT_WRITABLE", "Task not writable")
        if task.current_step not in WRITABLE_STEPS:
            raise AppError(409, "TASK_NOT_WRITABLE", "Task not cancellable")
        if expected_session_version != session.session_version:
            raise AppError(409, "STALE_STATE", "Session version mismatch", session_version=session.session_version)
        if expected_state_version != task.state_version:
            raise AppError(409, "STALE_STATE", "State version mismatch", state_version=task.state_version)

        result = self.db.execute(
            text(
                """
                UPDATE guide_tasks
                SET status = 'cancelled', current_step = 'cancelled',
                    state_version = state_version + 1, updated_at = :now
                WHERE task_id = :tid AND owner_id = :oid AND status = 'active'
                  AND state_version = :ver
                """
            ),
            {
                "tid": task_id,
                "oid": self.owner_id,
                "ver": expected_state_version,
                "now": datetime.now(timezone.utc),
            },
        )
        if result.rowcount != 1:
            raise AppError(409, "TASK_NOT_WRITABLE", "Could not cancel task")

        session.session_version += 1
        self.db.flush()
        task = self.db.get(GuideTask, task_id)
        if task:
            self.db.refresh(task)
        self.conversation.save_message(
            session.session_id,
            task_id=task_id,
            role="assistant",
            kind="action_result",
            content="已取消当前任务。",
            request_id=request_id,
        )
        response = {
            "task_id": task_id,
            "status": "cancelled",
            "state_version": task.state_version if task else expected_state_version + 1,
            "session_version": session.session_version,
        }
        op = self.operations.find("cancel", task_id, request_id)
        if op:
            self.operations.complete(op, response)
        self.db.commit()
        return response

    def create_task(
        self,
        session_id: str,
        *,
        request_id: str,
        expected_session_version: int,
        action: str,
        view_context: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.db.get(GuideSession, session_id)
        if not session or session.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
        digest = json.dumps(
            {"action": action, "expected_session_version": expected_session_version, "view": view_context},
            sort_keys=True,
        )
        cached = self.operations.check_or_begin(
            "create_task", "session", session_id, request_id, digest
        )
        if cached and cached.result_json:
            return json.loads(cached.result_json)
        if expected_session_version != session.session_version:
            raise AppError(409, "STALE_STATE", "Session version mismatch")

        if view_context:
            session.view_context_json = json.dumps(view_context)

        old_task = None
        if session.current_task_id:
            old_task = self.db.get(GuideTask, session.current_task_id)
            if old_task and effective_status(old_task) == "active":
                if old_task.current_step == "adding_to_cart":
                    raise AppError(409, "TASK_NOT_WRITABLE", "Task in confirmation")
                old_task.status = "superseded"
                old_task.terminal_reason = f"superseded_by:new"
                old_task.state_version += 1

        entry = json.loads(session.entry_context_json)
        if view_context:
            entry = {**entry, **view_context}

        req = Requirements()
        if action == "resume_last_goal":
            last = (
                self.db.query(GuideTask)
                .filter_by(session_id=session_id, owner_id=self.owner_id)
                .order_by(GuideTask.created_at.desc())
                .limit(5)
                .all()
            )
            goals = []
            for t in last:
                r = json.loads(t.requirements_json or "{}")
                if r.get("goal"):
                    goals.append(r["goal"])
            unique = list(dict.fromkeys(goals))
            if len(unique) != 1:
                response = {
                    "session_id": session_id,
                    "session_version": session.session_version,
                    "message": "请说明要继续哪个购买目标。",
                    "created": False,
                }
                op = self.operations.find("create_task", session_id, request_id)
                if op:
                    self.operations.complete(op, response)
                self.db.commit()
                return response
            req.goal = unique[0]
            if constraints and constraints.get("people"):
                req.people = constraints["people"]
        else:
            if constraints:
                req = Requirements.from_dict({**req.to_dict(), **constraints})

        task_id = new_task_id()
        state = TaskState(
            session_id=session_id,
            task_id=task_id,
            owner_id=self.owner_id,
            state_version=1,
            intent="purchase_task",
            entry_context=entry,
            requirements=req,
            current_step="understanding",
        )
        state.to_db(self.db, expected_version=None)
        session.current_task_id = task_id
        session.session_version += 1
        if old_task:
            old_task.terminal_reason = f"superseded_by:{task_id}"

        response = {
            "session_id": session_id,
            "task_id": task_id,
            "state_version": 1,
            "session_version": session.session_version,
            "created": True,
            "message": f"已开始新任务{f'：{req.goal}' if req.goal else ''}",
        }
        op = self.operations.find("create_task", session_id, request_id)
        if op:
            self.operations.complete(op, response)
        self.db.commit()
        return response

"""Persist and query guide conversation history."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.conversation import GuideMessage, PlanSnapshot
from app.models.session import GuideSession


class ConversationService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def _verify_session(self, session_id: str) -> GuideSession:
        session = self.db.get(GuideSession, session_id)
        if not session or session.owner_id != self.owner_id:
            raise PermissionError("SESSION_FORBIDDEN")
        return session

    def next_sequence(self, session_id: str) -> int:
        """Atomically allocate the next message sequence for a session."""
        self._verify_session(session_id)
        row = self.db.execute(
            text(
                """
                UPDATE guide_sessions
                SET message_seq = message_seq + 1
                WHERE session_id = :sid
                RETURNING message_seq
                """
            ),
            {"sid": session_id},
        ).fetchone()
        if not row:
            raise PermissionError("SESSION_FORBIDDEN")
        self.db.flush()
        return int(row[0])

    def save_message(
        self,
        session_id: str,
        *,
        task_id: str | None,
        role: str,
        kind: str,
        content: str,
        request_id: str | None = None,
        plan_id: str | None = None,
        plan_version: int | None = None,
        status: str = "completed",
        message_id: str | None = None,
    ) -> GuideMessage:
        seq = self.next_sequence(session_id)
        msg = GuideMessage(
            message_id=message_id or f"msg-{uuid4().hex[:12]}",
            session_id=session_id,
            task_id=task_id,
            sequence=seq,
            role=role,
            kind=kind,
            content=content,
            plan_id=plan_id,
            plan_version=plan_version,
            request_id=request_id,
            status=status,
        )
        self.db.add(msg)
        session = self.db.get(GuideSession, session_id)
        if session and session.history_status in ("empty", "unavailable"):
            session.history_status = "complete"
        return msg

    def save_plan_snapshot(
        self,
        session_id: str,
        task_id: str,
        plan: dict[str, Any],
        supply_context: dict[str, Any] | None = None,
    ) -> PlanSnapshot:
        """Persist an immutable plan snapshot.

        ``(plan_id, plan_version)`` is the snapshot identity, so re-confirming the
        very same version (a turn that re-prepared an unchanged plan) returns the
        stored snapshot instead of colliding with it.
        """
        existing = self.db.get(PlanSnapshot, (plan["plan_id"], plan["plan_version"]))
        if existing is not None:
            return existing
        snap = PlanSnapshot(
            plan_id=plan["plan_id"],
            plan_version=plan["plan_version"],
            task_id=task_id,
            session_id=session_id,
            plan_json=json.dumps(plan),
            supply_context_json=json.dumps(supply_context or {}),
        )
        self.db.add(snap)
        return snap

    def get_snapshot(self, plan_id: str, plan_version: int) -> dict[str, Any] | None:
        snap = self.db.get(PlanSnapshot, (plan_id, plan_version))
        if not snap:
            return None
        return json.loads(snap.plan_json)

    def list_messages(
        self,
        session_id: str,
        *,
        cursor: int | None = None,
        limit: int = 50,
        direction: str = "backward",
    ) -> dict[str, Any]:
        self._verify_session(session_id)
        q = self.db.query(GuideMessage).filter_by(session_id=session_id)
        q = q.filter(~GuideMessage.content.like("方案已更新%"))
        if cursor is not None:
            if direction == "backward":
                q = q.filter(GuideMessage.sequence < cursor)
            else:
                q = q.filter(GuideMessage.sequence > cursor)
        if direction == "backward":
            rows = q.order_by(GuideMessage.sequence.desc()).limit(limit).all()
            rows = list(reversed(rows))
        else:
            rows = q.order_by(GuideMessage.sequence.asc()).limit(limit).all()
        has_more = False
        next_cursor = None
        if rows:
            next_cursor = rows[0].sequence
            if direction == "backward":
                older = (
                    self.db.query(GuideMessage)
                    .filter(
                        GuideMessage.session_id == session_id,
                        GuideMessage.sequence < next_cursor,
                        ~GuideMessage.content.like("方案已更新%"),
                    )
                    .count()
                )
                has_more = older > 0
        return {
            "messages": [
                {
                    "message_id": m.message_id,
                    "session_id": m.session_id,
                    "task_id": m.task_id,
                    "sequence": m.sequence,
                    "role": m.role,
                    "kind": m.kind,
                    "content": m.content,
                    "plan_id": m.plan_id,
                    "plan_version": m.plan_version,
                    "request_id": m.request_id,
                    "status": m.status,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
            ],
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    def message_to_dict(self, m: GuideMessage) -> dict[str, Any]:
        return {
            "message_id": m.message_id,
            "session_id": m.session_id,
            "task_id": m.task_id,
            "sequence": m.sequence,
            "role": m.role,
            "kind": m.kind,
            "content": m.content,
            "plan_id": m.plan_id,
            "plan_version": m.plan_version,
            "request_id": m.request_id,
            "status": m.status,
        }

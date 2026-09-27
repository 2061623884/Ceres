"""Trace recording and retrieval."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.trace import Badcase, BusinessEvent, TraceEvent


def _redact(text: str | None) -> str | None:
    if not text:
        return text
    text = re.sub(r"\b1[3-9]\d{9}\b", "[PHONE]", text)
    text = re.sub(r"sk-[a-zA-Z0-9]{10,}", "[API_KEY]", text)
    return text


class TraceService:
    def __init__(self, db: Session):
        self.db = db

    def commit_independent(self) -> None:
        """Persist trace rows even when the surrounding business transaction rolls back."""
        self.db.commit()

    def record(
        self,
        *,
        trace_id: str,
        request_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        owner_id: str | None = None,
        phase: str,
        model_mode: str = "mock",
        input_summary: str | None = None,
        output_summary: str | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> str:
        event_id = f"evt-{uuid4().hex[:12]}"
        self.db.add(
            TraceEvent(
                event_id=event_id,
                trace_id=trace_id,
                request_id=request_id,
                session_id=session_id,
                task_id=task_id,
                owner_id=owner_id,
                phase=phase,
                model_mode=model_mode,
                input_summary=_redact(input_summary),
                output_summary=_redact(output_summary),
                error=_redact(error),
                duration_ms=duration_ms,
            )
        )
        self.db.flush()
        return event_id

    def list_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = (
            self.db.query(TraceEvent)
            .order_by(TraceEvent.created_at.desc())
            .limit(limit * 3)
            .all()
        )
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            if row.trace_id in seen:
                continue
            seen.add(row.trace_id)
            result.append(
                {
                    "trace_id": row.trace_id,
                    "session_id": row.session_id,
                    "task_id": row.task_id,
                    "phase": row.phase,
                    "model_mode": row.model_mode,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
            if len(result) >= limit:
                break
        return result

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        rows = (
            self.db.query(TraceEvent)
            .filter_by(trace_id=trace_id)
            .order_by(TraceEvent.created_at.asc())
            .all()
        )
        if not rows:
            return None
        events = [
            {
                "event_id": r.event_id,
                "phase": r.phase,
                "model_mode": r.model_mode,
                "input_summary": r.input_summary,
                "output_summary": r.output_summary,
                "error": r.error,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        first = rows[0]
        return {
            "trace_id": trace_id,
            "request_id": first.request_id,
            "session_id": first.session_id,
            "task_id": first.task_id,
            "events": events,
            "event_count": len(events),
        }

    def record_event(
        self,
        owner_id: str,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        task_id: str | None = None,
        model_mode: str = "mock",
        client_event_id: str | None = None,
        source: str = "server",
    ) -> str:
        if client_event_id:
            existing = (
                self.db.query(BusinessEvent)
                .filter_by(owner_id=owner_id, client_event_id=client_event_id)
                .first()
            )
            if existing:
                return existing.event_id
        if source == "client" and event_type in {"plan_confirmed", "cart_add_succeeded"}:
            raise ValueError(f"{event_type} must be recorded server-side only")
        event_id = f"evt-{uuid4().hex[:12]}"
        self.db.add(
            BusinessEvent(
                event_id=event_id,
                owner_id=owner_id,
                session_id=session_id,
                task_id=task_id,
                event_type=event_type,
                payload_json=json.dumps(payload),
                model_mode=model_mode,
                client_event_id=client_event_id,
                source=source,
            )
        )
        return event_id


class BadcaseService:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        trace_id: str,
        category: str,
        expected_behavior: str,
        actual_behavior: str,
        severity: str = "medium",
    ) -> dict[str, Any]:
        badcase_id = f"bc-{uuid4().hex[:8]}"
        self.db.add(
            Badcase(
                id=badcase_id,
                trace_id=trace_id,
                category=category,
                severity=severity,
                expected_behavior=expected_behavior,
                actual_behavior=actual_behavior,
            )
        )
        self.db.commit()
        return {"id": badcase_id, "trace_id": trace_id, "status": "open"}

    def update_status(self, badcase_id: str, status: str) -> dict[str, Any] | None:
        bc = self.db.get(Badcase, badcase_id)
        if not bc:
            return None
        bc.status = status
        return {"id": bc.id, "status": bc.status}

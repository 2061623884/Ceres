"""Post-reply extraction and infrequent Dream on an independent session."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.errors import LLMProviderError
from app.llm.memory_provider import MemoryProvider, MemoryOutput
from app.models.memory import ShoppingMemory
from app.models.trace import TraceEvent
from app.services.memory_service import MemoryService
from app.services.trace_service import TraceService


class AutomaticMemoryService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def process_turn(self, *, session_id: str, request_id: str, trace_id: str, message: str, reply: str) -> None:
        # A durable start also prevents a replay while the model is still pending.
        done = self.db.scalar(select(TraceEvent.event_id).where(
            TraceEvent.owner_id == self.owner_id, TraceEvent.session_id == session_id,
            TraceEvent.request_id == request_id,
            TraceEvent.phase.in_(("memory_extract_started", "memory_extract_completed", "memory_background_failed")),
        ).limit(1))
        if done is not None:
            return
        try:
            TraceService(self.db).record(trace_id=trace_id, owner_id=self.owner_id,
                session_id=session_id, request_id=request_id, phase="memory_extract_started",
                model_mode=get_settings().llm_mode,
                output_summary=json.dumps({"model": get_settings().memory_model}))
            self.db.commit()
            existing = MemoryService(self.db, self.owner_id).list_valid()
            output = MemoryProvider().complete("extract", {
                "message": message, "reply": reply, "memories": [row.to_dict() for row in existing],
            })
            if output.drop_refs:
                raise AppError(422, "INVALID_MEMORY_OUTPUT", "自动提取不能删除记忆。")
            self.db.expire_all()
            existing = MemoryService(self.db, self.owner_id).list_valid()
            saved = self._save(output, existing, renew_existing=True)
            TraceService(self.db).record(trace_id=trace_id, owner_id=self.owner_id,
                session_id=session_id, request_id=request_id, phase="memory_extract_completed",
                model_mode=get_settings().llm_mode,
                output_summary=json.dumps({"saved": saved, "model": get_settings().memory_model}))
            self.db.commit()
            self.dream_if_due(trace_id=trace_id)
        except (LLMProviderError, AppError) as exc:
            self.db.rollback()
            code = exc.code if isinstance(exc, LLMProviderError) else exc.detail["error"]["code"]
            detail = exc.message if isinstance(exc, LLMProviderError) else exc.detail["error"]["message"]
            TraceService(self.db).record(trace_id=trace_id, owner_id=self.owner_id,
                session_id=session_id, request_id=request_id, phase="memory_background_failed",
                model_mode=get_settings().llm_mode, error=code,
                output_summary=json.dumps({"model": get_settings().memory_model, "message": detail}))
            self.db.commit()

    def _save(self, output: MemoryOutput, existing: list[ShoppingMemory], *, renew_existing: bool) -> int:
        explicit_refs = {row.memory_id for row in existing if row.source == "explicit"}
        saved = 0
        for item in output.memories:
            if explicit_refs.intersection(item.conflicts_with):
                continue
            row = next((row for row in existing if row.category == item.category and row.content == item.content), None)
            if row is not None and (row.source == "explicit" or not renew_existing):
                continue
            now = datetime.now(timezone.utc)
            if row is None:
                row = ShoppingMemory(memory_id="memory-" + uuid4().hex, owner_id=self.owner_id,
                                     category=item.category, content=item.content, source="automatic")
                self.db.add(row)
                existing.append(row)
            row.expires_at = now + timedelta(days=30)
            row.updated_at = now
            saved += 1
        self.db.flush()
        return saved

    def dream_if_due(self, *, trace_id: str) -> bool:
        now = datetime.now(timezone.utc)
        valid = MemoryService(self.db, self.owner_id).list_valid()
        automatic = [row for row in valid if row.source == "automatic"]
        last = self.db.scalar(select(TraceEvent.created_at).where(
            TraceEvent.owner_id == self.owner_id, TraceEvent.phase == "memory_dream_completed",
        ).order_by(TraceEvent.created_at.desc()).limit(1))
        if len(automatic) < 10 or (last is not None and now - last.replace(tzinfo=timezone.utc) < timedelta(hours=24)):
            return False
        output = MemoryProvider().complete("dream", {"memories": [row.to_dict() for row in valid]})
        self.db.expire_all()
        valid = MemoryService(self.db, self.owner_id).list_valid()
        automatic = [row for row in valid if row.source == "automatic"]
        editable = {row.memory_id: row for row in automatic}
        if any(ref not in editable for ref in output.drop_refs):
            raise AppError(422, "INVALID_MEMORY_OUTPUT", "Dream 只能删除当前用户的有效自动记忆。")
        for ref in output.drop_refs:
            self.db.delete(editable[ref])
        expired = list(self.db.scalars(select(ShoppingMemory).where(
            ShoppingMemory.owner_id == self.owner_id, ShoppingMemory.source == "automatic",
            ShoppingMemory.expires_at <= now,
        )))
        for row in expired:
            self.db.delete(row)
        self.db.flush()
        self._save(output, [row for row in valid if row.memory_id not in output.drop_refs], renew_existing=False)
        TraceService(self.db).record(trace_id=trace_id, owner_id=self.owner_id,
            phase="memory_dream_completed", model_mode=get_settings().llm_mode,
            output_summary=json.dumps({"model": get_settings().memory_model,
                                       "deleted": len(output.drop_refs) + len(expired)}))
        self.db.commit()
        return True

"""Guide operation idempotency and lookup."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.conversation import GuideOperation


class OperationService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def find(
        self,
        op_type: str,
        scope_id: str,
        request_id: str,
    ) -> GuideOperation | None:
        return (
            self.db.query(GuideOperation)
            .filter_by(
                owner_id=self.owner_id,
                op_type=op_type,
                scope_id=scope_id,
                request_id=request_id,
            )
            .first()
        )

    def check_or_begin(
        self,
        op_type: str,
        scope_type: str,
        scope_id: str,
        request_id: str,
        request_digest: str,
        in_progress_code: str = "TURN_IN_PROGRESS",
    ) -> GuideOperation | None:
        existing = self.find(op_type, scope_id, request_id)
        if existing:
            if existing.request_digest != request_digest:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Request ID reused with different body")
            if existing.status == "completed" and existing.result_json:
                return existing
            if existing.status == "pending":
                raise AppError(409, in_progress_code, "Operation already in progress")
        op = GuideOperation(
            operation_id=f"gop-{uuid4().hex[:12]}",
            owner_id=self.owner_id,
            op_type=op_type,
            scope_type=scope_type,
            scope_id=scope_id,
            request_id=request_id,
            request_digest=request_digest,
            status="pending",
        )
        self.db.add(op)
        self.db.flush()
        return None

    def complete(self, op: GuideOperation, result: dict[str, Any]) -> None:
        op.status = "completed"
        op.result_json = json.dumps(result)

    def fail(self, op: GuideOperation, retryable: bool = True) -> None:
        op.status = "retryable_failed" if retryable else "final_failed"

    def list_by_request(self, op_type: str, request_id: str) -> list[GuideOperation]:
        return (
            self.db.query(GuideOperation)
            .filter_by(owner_id=self.owner_id, op_type=op_type, request_id=request_id)
            .all()
        )

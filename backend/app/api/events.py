"""Client event ingestion."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.identity import get_or_create_owner
from app.services.trace_service import TraceService

router = APIRouter(prefix="/api/v1", tags=["events"])

CLIENT_ALLOWED_EVENTS = {
    "guide_opened",
    "task_started",
    "clarification_asked",
    "plan_ready",
    "plan_viewed",
    "plan_modified",
    "task_cancelled",
    "task_degraded",
    "feedback_submitted",
}

SERVER_ONLY_EVENTS = {"plan_confirmed", "cart_add_succeeded", "cart_add_failed"}


class ClientEvent(BaseModel):
    event_type: str
    session_id: str | None = None
    task_id: str | None = None
    payload: dict = Field(default_factory=dict)
    client_event_id: str | None = None


class EventsBatch(BaseModel):
    events: list[ClientEvent]


@router.post("/events")
def post_events(
    body: EventsBatch,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = get_or_create_owner(request, response, db)
    settings = get_settings()
    trace = TraceService(db)
    accepted = []
    rejected = []
    for evt in body.events:
        if evt.event_type in SERVER_ONLY_EVENTS:
            rejected.append({"event_type": evt.event_type, "reason": "server_only"})
            continue
        if evt.event_type not in CLIENT_ALLOWED_EVENTS:
            rejected.append({"event_type": evt.event_type, "reason": "not_allowed"})
            continue
        if not evt.client_event_id:
            rejected.append({"event_type": evt.event_type, "reason": "missing_client_event_id"})
            continue
        try:
            trace.record_event(
                owner_id,
                evt.event_type,
                evt.payload,
                session_id=evt.session_id,
                task_id=evt.task_id,
                model_mode=settings.llm_mode,
                client_event_id=evt.client_event_id,
                source="client",
            )
            accepted.append(evt.client_event_id)
        except ValueError as exc:
            rejected.append({"event_type": evt.event_type, "reason": str(exc)})
    if rejected and not accepted:
        raise AppError(422, "INVALID_INPUT", "No client events accepted", retryable=False)
    db.commit()
    return {"accepted": accepted, "rejected": rejected}

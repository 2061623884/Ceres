"""Mercury consultation of this anonymous owner's persistent orders."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette import EventSourceResponse

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.identity import get_or_create_owner
from app.models.order import MercurySession
from app.services.order_service import OrderService

mercury_path = Path(__file__).resolve().parents[3] / "Mercury"
if str(mercury_path) not in sys.path:
    sys.path.insert(0, str(mercury_path))

from mercury.agent import MercuryModelError, run_mercury
from mercury.llm import OpenAIChatClient

router = APIRouter(prefix="/api/v1/mercury", tags=["mercury"])


def _owner(request: Request, response: Response, db: Session = Depends(get_db)) -> str:
    return get_or_create_owner(request, response, db)


def _session(db: Session, owner_id: str, session_id: str) -> MercurySession:
    session = db.query(MercurySession).filter_by(session_id=session_id, owner_id=owner_id).first()
    if session is None:
        raise AppError(404, "SESSION_NOT_FOUND", "没有找到这个售后会话")
    return session


class TurnRequest(BaseModel):
    message: str
    request_id: str


class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    selected_order_id: str | None


class SelectOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)


@router.post("/sessions", response_model=SessionResponse)
def create_mercury_session(owner_id: str = Depends(_owner), db: Session = Depends(get_db)):
    session = MercurySession(session_id=f"ms_{uuid4().hex[:12]}", owner_id=owner_id)
    db.add(session)
    db.commit()
    return SessionResponse(session_id=session.session_id, created_at=session.created_at,
                           selected_order_id=session.selected_order_id)


@router.post("/sessions/{session_id}/order")
def select_order(session_id: str, body: SelectOrderRequest, owner_id: str = Depends(_owner),
                 db: Session = Depends(get_db)):
    session = _session(db, owner_id, session_id)
    order = OrderService(db, owner_id).get_order(body.order_id)
    session.selected_order_id = order["order_id"]
    db.commit()
    return {"session_id": session_id, "order": order}


@router.post("/sessions/{session_id}/turns/stream")
def mercury_turn_stream(session_id: str, request: TurnRequest, owner_id: str = Depends(_owner),
                        db: Session = Depends(get_db)):
    return mercury_response(session_id, request, owner_id, db)


def mercury_response(session_id: str, request: TurnRequest, owner_id: str, db: Session,
                     handoff_context: dict | None = None):
    session = _session(db, owner_id, session_id)
    selected_order_id = session.selected_order_id
    orders = OrderService(db, owner_id).list_orders() if selected_order_id is None else None
    settings = get_settings()
    database_path = str(db.get_bind().url.database)

    async def event_generator():
        yield {"event": "accepted", "data": json.dumps({"request_id": request.request_id})}
        if selected_order_id is None:
            yield {"event": "orders", "data": json.dumps({"items": orders}, ensure_ascii=False)}
        llm = OpenAIChatClient({"base_url": settings.openai_base_url, "api_key": settings.openai_api_key,
                                "model": settings.llm_model, "timeout": settings.llm_timeout,
                                "max_output_tokens": settings.llm_max_output_tokens})
        try:
            response_text = await asyncio.to_thread(run_mercury, owner_id, request.message, llm,
                                                   database_path=database_path, session_id=session_id,
                                                   selected_order_id=selected_order_id,
                                                   handoff_context=handoff_context)
        except MercuryModelError as exc:
            yield {"event": "error", "data": json.dumps({"code": "MERCURY_MODEL_FAILED",
                "message": "服务暂时不可用，本轮未完成。", "cause": str(exc)}, ensure_ascii=False)}
            return
        yield {"event": "answer.delta", "data": json.dumps({"text": response_text}, ensure_ascii=False)}
        yield {"event": "turn.completed", "data": json.dumps({"session_id": session_id,
                                                                "final_text": response_text}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())

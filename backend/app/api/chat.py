"""V3 entry before either role's unchanged business/SSE transport."""
import asyncio
import hashlib
import json
from time import perf_counter
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette import ServerSentEvent

from app.api.guide import process_guide_turn_stream
from app.api.mercury import TurnRequest as MercuryTurnRequest, mercury_response
from app.core.database import get_db
from app.core.errors import AppError
from app.core.identity import get_or_create_owner
from app.llm.kev_provider import CRITERIA_VERSION, KevUnavailable, get_kev_provider
from app.models.order import MercurySession
from app.models.session import GuideSession, GuideTask
from app.schemas.guide import TurnRequest
from app.services.chat_opening_service import Handoff, Opening, chat_openings
from app.agent.context_resolver import ContextResolver
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/chat", tags=["v3-chat"])


@router.get("/demo")
def demo():
    from pathlib import Path
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parents[3] / "work/ceres-v3/03/demo.html")


def owner(request: Request, response: Response, db: Session = Depends(get_db)) -> str:
    return get_or_create_owner(request, response, db)


class OpenRequest(BaseModel):
    guide_session_id: str
    mercury_session_id: str
    role: Literal["keke", "momo"] = "keke"


class ChatTurnRequest(TurnRequest):
    order_id: str | None = Field(None, max_length=64)


class DisplayRequest(BaseModel):
    handoff_id: str


class SwitchRequest(BaseModel):
    target_role: Literal["keke", "momo"]
    handoff_id: str | None = None
    accept: bool


def packet(opening: Opening, event_type: str, payload: dict) -> str:
    if opening.role == "momo":
        return ServerSentEvent(event=event_type, data=json.dumps(payload, ensure_ascii=False)).encode().decode()
    return "data: " + json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False) + "\n\n"


def stream(generator):
    return StreamingResponse(generator, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.post("/openings")
def open_chat(body: OpenRequest, owner_id: str = Depends(owner), db: Session = Depends(get_db)):
    guide = db.get(GuideSession, body.guide_session_id)
    momo = db.get(MercurySession, body.mercury_session_id)
    if guide is None or momo is None or guide.owner_id != owner_id or momo.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "会话不属于当前用户。")
    return chat_openings.create(owner_id, guide.session_id, momo.session_id, body.role).view()


@router.get("/openings/{opening_id}")
def get_chat(opening_id: str, owner_id: str = Depends(owner)):
    opening = chat_openings.require(opening_id, owner_id)
    with opening.lock:
        opening.require_open()
        return opening.view()


@router.delete("/openings/{opening_id}", status_code=204)
def close_chat(opening_id: str, owner_id: str = Depends(owner)):
    chat_openings.close(opening_id, owner_id)
    return Response(status_code=204)


@router.post("/openings/{opening_id}/prompt-displayed")
def displayed(opening_id: str, body: DisplayRequest, owner_id: str = Depends(owner)):
    opening = chat_openings.require(opening_id, owner_id)
    with opening.lock:
        opening.require_open()
        if opening.pending is None or opening.pending.handoff_id != body.handoff_id:
            raise AppError(409, "HANDOFF_STALE", "这个切换建议已失效。")
        opening.prompt_displayed = True
        return opening.view()


def route_context(db: Session, opening: Opening, body: ChatTurnRequest) -> dict:
    ctx = ContextResolver(db, opening.owner_id).resolve(opening.guide_session_id, message_limit=6)
    if body.order_id is None:
        named_orders = [row["order_id"] for row in OrderService(db, opening.owner_id).list_orders()
                        if row["order_id"] in body.message]
        if len(named_orders) == 1:
            body.order_id = named_orders[0]
    momo = db.get(MercurySession, opening.mercury_session_id)
    selected_order_id = body.order_id or (momo.selected_order_id if opening.role == "momo" else None)
    if selected_order_id:
        order = OrderService(db, opening.owner_id).get_order(selected_order_id)
        selected = {"kind": "placed_order", "order_id": order["order_id"]}
    else:
        view = body.view_context.model_dump() if body.view_context else ctx.view
        selected = {"kind": "shopping", "view": view, "purchase_summary": ctx.purchase_summary}
        if not ctx.purchase_summary and not view.get("product_id") and not view.get("activity_id"):
            selected = None
    recent = [{"role": row["role"], "content": row["content"]} for row in ctx.recent_messages]
    if opening.role == "momo":
        from mercury.agent import recent_session_dialogue
        recent = recent_session_dialogue(opening.owner_id, opening.mercury_session_id, selected_order_id)
        if selected_order_id is None:
            selected = None
    return {"current_role": "Keke shopping" if opening.role == "keke" else "Momo after-sales", "selected_object": selected,
        "recent_dialogue": [*recent, *opening.recent_dialogue][-6:], "utterance": body.message,
        "pending_question": opening.pending_question}


async def business(opening: Opening, body: ChatTurnRequest, request: Request,
                   response: Response, db: Session, handoff: Handoff | None = None):
    if opening.role == "keke":
        guide_body = TurnRequest.model_validate(body.model_dump(exclude={"order_id"}))
        handoff_recent_messages = handoff.context["recent_dialogue"] if handoff else None
        result = await process_guide_turn_stream(
            opening.guide_session_id, guide_body, request, response, db,
            owner_id=opening.owner_id,
            handoff_recent_messages=handoff_recent_messages,
        )
    else:
        if handoff or body.order_id is not None:
            order = OrderService(db, opening.owner_id).get_order(body.order_id) if body.order_id else None
            momo = db.get(MercurySession, opening.mercury_session_id)
            momo.selected_order_id = order["order_id"] if order else None
            db.commit()
        result = mercury_response(opening.mercury_session_id,
            MercuryTurnRequest(message=body.message, request_id=body.request_id),
            owner_id=opening.owner_id, db=db,
            handoff_context=handoff.context if handoff else None)
    async for chunk in result.body_iterator:
        if isinstance(chunk, dict):
            yield ServerSentEvent(**chunk).encode().decode()
        else:
            yield chunk.decode() if isinstance(chunk, bytes) else chunk


def failed_chunk(chunk: str) -> bool:
    lines = chunk.replace("\r\n", "\n").splitlines()
    named = next((line[7:] for line in lines if line.startswith("event: ")), None)
    raw = next((line[6:] for line in lines if line.startswith("data: ")), None)
    if raw is None:  # Existing SSE transport can also send heartbeat comments.
        return False
    event = json.loads(raw)
    event_type = named if named else event["type"]
    payload = event if named else event["payload"]
    return event_type in ("error", "turn.stopped") or payload.get("answer_status") == "failed"


@router.post("/openings/{opening_id}/turns/stream")
async def chat_turn(opening_id: str, body: ChatTurnRequest, request: Request, response: Response,
                    owner_id: str = Depends(owner), db: Session = Depends(get_db)):
    opening = chat_openings.require(opening_id, owner_id)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    with opening.lock:
        opening.require_open()
        existing = opening.requests.get(body.request_id)
        if existing:
            if existing["digest"] != digest:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "同一请求标识的消息不能改变。")
            if existing["status"] != "completed":
                raise AppError(409, "TURN_IN_PROGRESS", "此消息尚未完成，请勿重复提交。")
            async def replay():
                for chunk in existing["chunks"]:
                    yield chunk
            return stream(replay())
        if opening.busy:
            raise AppError(409, "TURN_IN_PROGRESS", "当前聊天仍在处理上一条消息。")
        started = perf_counter()
        context = route_context(db, opening, body)
        db.commit()  # Validate owner/object before SSE headers; no transaction during Kev.
        opening.busy = True
        receipt = {"digest": digest, "status": "processing", "chunks": []}
        opening.requests[body.request_id] = receipt

    async def generate():
        try:
            try:
                answer, raw = await asyncio.to_thread(get_kev_provider().decide, context)
                route = {"status": "completed", "decision": answer.choice, "raw_choice": answer.choice,
                         "probabilities": answer.probabilities, "raw_response": raw}
            except KevUnavailable as exc:
                route = {"status": "unavailable", "decision": None, "error": str(exc),
                    "message": "自动路由暂不可用，可继续当前角色业务或用固定入口切换。"}
            route.update(request_id=body.request_id, current_role=opening.role,
                criteria_version=CRITERIA_VERSION, route_ms=(perf_counter() - started) * 1000,
                manual_switch_available=True, prompt_mode="none")
            # A new request replaces the old pending intention, including stay/clarify.
            opening.pending = None
            opening.pending_question = None
            opening.recent_dialogue = [*opening.recent_dialogue,
                {"role": "user", "content": body.message}][-6:]
            if route["decision"] == "suggest_switch":
                target_role = "momo" if opening.role == "keke" else "keke"
                opening.pending = Handoff(f"handoff_{uuid4().hex}", body.request_id, target_role, body.model_dump(), context)
                route.update(target_role=target_role, handoff_id=opening.pending.handoff_id,
                    prompt_mode="fixed_entry" if opening.prompt_displayed else "automatic")
            chunk = packet(opening, "service.route", route)
            receipt["chunks"].append(chunk)
            yield chunk
            if route["decision"] in ("suggest_switch", "clarify"):
                boundary = "订单业务由墨墨处理" if opening.role == "keke" else "选购业务由可可处理"
                text = (boundary + ("，是否切换？" if route["prompt_mode"] == "automatic"
                    else "，可用固定入口切换。")) if route["decision"] == "suggest_switch" else "你指的是正在选购的商品或采购清单项，还是已下单订单？"
                opening.pending_question = text
                chunk = packet(opening, "turn.completed", {"message": text, "business_not_run": True})
                receipt["chunks"].append(chunk)
                yield chunk
            else:
                async for chunk in business(opening, body, request, response, db):
                    receipt["chunks"].append(chunk)
                    yield chunk
            receipt["status"] = "completed"
        finally:
            opening.busy = False
    return stream(generate())


@router.post("/openings/{opening_id}/switches/stream")
async def switch_chat(opening_id: str, body: SwitchRequest, request: Request, response: Response,
                      owner_id: str = Depends(owner), db: Session = Depends(get_db)):
    opening = chat_openings.require(opening_id, owner_id)
    with opening.lock:
        opening.require_open()
        handoff = opening.pending
        if body.handoff_id is not None and (handoff is None or handoff.handoff_id != body.handoff_id or handoff.target_role != body.target_role):
            raise AppError(409, "HANDOFF_STALE", "这个交接已失效。")
        if body.handoff_id is None and (handoff is None or handoff.target_role != body.target_role or handoff.status in ("completed", "failed")):
            if opening.busy:
                raise AppError(409, "TURN_IN_PROGRESS", "当前聊天仍在处理上一条消息。")
            if body.accept:
                opening.role = body.target_role
            async def restored():
                yield packet(opening, "service.switch", {"status": "resumed", **opening.view()})
            return stream(restored())
        if not body.accept:
            if handoff.status == "pending":
                opening.pending_question = None
            async def rejected():
                yield packet(opening, "service.switch", {"status": "rejected", "role": opening.role})
            return stream(rejected())
        if handoff.status in ("completed", "failed"):
            async def replay():
                for chunk in handoff.chunks:
                    yield chunk
            return stream(replay())
        if opening.busy or handoff.status != "pending":
            raise AppError(409, "HANDOFF_IN_PROGRESS", "此交接尚未完成，不能再次处理。")
        opening.pending_question = None
        opening.busy = True
        handoff.status = "processing"
        opening.role = body.target_role
    async def generate():
        try:
            turn = ChatTurnRequest.model_validate(handoff.body)
            turn.request_id = "handoff_" + handoff.handoff_id
            if body.target_role == "keke":
                guide = db.get(GuideSession, opening.guide_session_id)
                turn.expected_task_id = guide.current_task_id
                turn.expected_state_version = (
                    db.get(GuideTask, guide.current_task_id).state_version
                    if guide.current_task_id else 0
                )
                turn.expected_session_version = guide.session_version
            failed = False
            async for chunk in business(opening, turn, request, response, db, handoff):
                failed = failed or failed_chunk(chunk)
                handoff.chunks.append(chunk)
                yield chunk
            handoff.status = "failed" if failed else "completed"
        finally:
            opening.busy = False
    return stream(generate())

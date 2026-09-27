"""Guide session and turn API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.identity import get_or_create_owner
from app.models.cart import CartOperation
from app.models.conversation import GuideOperation
from app.models.session import GuideSession, GuideTask
from app.schemas.guide import (
    AddPlanItemRequest,
    AddPlanItemResponse,
    CancelRequest,
    CancelResponse,
    ConfirmRequest,
    ConfirmResponse,
    CreateTaskRequest,
    EntryContext,
    MessagesPageResponse,
    PlanResponse,
    PlanRefreshRequest,
    PlanRefreshResponse,
    PlanRevisionRequest,
    PlanRevisionResponse,
    SessionCreateRequest,
    SessionResponse,
    SupplyContextRequest,
    StopTurnRequest,
    StopTurnResponse,
    TurnRequest,
)
from app.services.cart_service import CartService
from app.services.confirmation_service import ConfirmationService
from app.services.conversation_service import ConversationService
from app.services.plan_item_service import PlanItemService
from app.services.plan_refresh_service import PlanRefreshService
from app.services.plan_revision_service import PlanRevisionService
from app.services.session_actions import available_actions_for_task, effective_status
from app.services.task_lifecycle_service import TaskLifecycleService
from app.services.turn_stream_service import TurnStreamService

router = APIRouter(prefix="/api/v1", tags=["guide"])


def _owner(request: Request, response: Response, db: Session) -> str:
    return get_or_create_owner(request, response, db)


def _session_response(
    db: Session,
    session: GuideSession,
    *,
    include_messages: bool = False,
) -> SessionResponse:
    from app.agent.context import pending_for_session

    entry = EntryContext(**json.loads(session.entry_context_json))
    task_id = session.current_task_id
    plan = None
    step = None
    version = 0
    message = None
    task_status = None
    available_actions: list[str] = ["send_message"]
    constraints_summary: dict = {}
    cart_version = None
    confirmation_id = None
    confirmation_result = None
    if task_id:
        task = db.get(GuideTask, task_id)
        if task:
            version = task.state_version
            step = task.current_step
            task_status = effective_status(task)
            req = json.loads(task.requirements_json or "{}")
            constraints_summary = {
                "goal": req.get("goal"),
                "people": req.get("people"),
                "budget_fen": req.get("budget_fen"),
                "excluded_ingredients": req.get("excluded_ingredients") or [],
            }
            confirmation_id = task.confirmation_id
            available_actions = available_actions_for_task(task)
            if task.cart_result_json:
                cart_result = json.loads(task.cart_result_json)
                cart_version = cart_result.get("cart_version")
                confirmation_result = cart_result
            if step == "awaiting_confirmation" and task.status == "active" and task.plan_json:
                p = json.loads(task.plan_json)
                plan = PlanResponse(**p)
                message = "已恢复待确认方案"
            elif task_status in ("completed", "cancelled", "superseded"):
                if task_status == "completed" and task.plan_json:
                    p = json.loads(task.plan_json)
                    plan = PlanResponse(**p)
                    message = "任务已完成，以下为历史方案"
                elif task_status == "cancelled":
                    message = "任务已取消"
            elif task.plan_json:
                p = json.loads(task.plan_json)
                plan = PlanResponse(**p)

    messages = None
    if include_messages:
        conv = ConversationService(db, session.owner_id)
        page = conv.list_messages(session.session_id, limit=50)
        messages = page["messages"]

    return SessionResponse(
        session_id=session.session_id,
        task_id=task_id,
        state_version=version,
        session_version=session.session_version,
        current_step=step,
        task_status=task_status,
        entry_context=entry,
        plan=plan,
        # A finished task's plan is a deliverable, not something to keep buying
        # from: the snapshot stays available for the dock, read-only.
        plan_read_only=bool(plan) and task_status in ("completed", "cancelled", "superseded"),
        pending_clarifications=pending_for_session(db, session),
        confirmation_result=confirmation_result,
        message=message,
        available_actions=available_actions,
        constraints_summary=constraints_summary,
        cart_version=cart_version,
        confirmation_id=confirmation_id,
        history_status=session.history_status,
        messages=messages,
    )


@router.post("/guide/sessions", response_model=SessionResponse)
def create_session(
    body: SessionCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    session_id = f"sess-{uuid4().hex[:12]}"
    ctx = body.entry_context
    db.add(
        GuideSession(
            session_id=session_id,
            owner_id=owner_id,
            entry_context_json=json.dumps(ctx.model_dump()),
            supply_store_id=ctx.store_id,
            supply_zone_id=ctx.delivery_zone_id,
            view_context_json=json.dumps({"page": ctx.page, "category_id": ctx.category_id}),
            history_status="empty",
        )
    )
    db.commit()
    session = db.get(GuideSession, session_id)
    return _session_response(db, session)


@router.get("/guide/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    request: Request,
    response: Response,
    include_messages: int = Query(0, alias="include_messages"),
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    session = db.get(GuideSession, session_id)
    if not session or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
    if session.history_status in ("empty", None):
        from app.models.conversation import GuideMessage

        has_msgs = db.query(GuideMessage).filter_by(session_id=session_id).count() > 0
        if has_msgs:
            session.history_status = "complete"
        elif session.current_task_id:
            session.history_status = "unavailable"
    return _session_response(db, session, include_messages=bool(include_messages))


@router.get("/guide/sessions/{session_id}/messages", response_model=MessagesPageResponse)
def list_messages(
    session_id: str,
    request: Request,
    response: Response,
    cursor: int | None = None,
    limit: int = Query(50, ge=1, le=100),
    direction: str = Query("backward"),
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    session = db.get(GuideSession, session_id)
    if not session or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
    conv = ConversationService(db, owner_id)
    page = conv.list_messages(session_id, cursor=cursor, limit=limit, direction=direction)
    return MessagesPageResponse(
        messages=page["messages"],
        has_more=page["has_more"],
        next_cursor=page["next_cursor"],
        history_status=session.history_status,
    )


@router.post("/guide/sessions/{session_id}/tasks")
def create_task(
    session_id: str,
    body: CreateTaskRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    svc = TaskLifecycleService(db, owner_id)
    view = body.view_context.model_dump() if body.view_context else None
    try:
        return svc.create_task(
            session_id,
            request_id=body.request_id,
            expected_session_version=body.expected_session_version,
            action=body.action,
            view_context=view,
            constraints=body.constraints,
        )
    except Exception as exc:
        from sqlalchemy.exc import OperationalError

        if isinstance(exc, OperationalError) and "locked" in str(exc).lower():
            raise AppError(503, "DB_BUSY", "服务忙，请稍后重试", retryable=True) from exc
        raise


@router.post("/guide/sessions/{session_id}/supply-context")
def update_supply_context(
    session_id: str,
    body: SupplyContextRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    session = db.get(GuideSession, session_id)
    if not session or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
    if body.expected_session_version != session.session_version:
        raise AppError(409, "STALE_STATE", "Session version mismatch")
    session.supply_store_id = body.store_id
    session.supply_zone_id = body.delivery_zone_id
    session.session_version += 1
    entry = json.loads(session.entry_context_json)
    entry["store_id"] = body.store_id
    entry["delivery_zone_id"] = body.delivery_zone_id
    session.entry_context_json = json.dumps(entry)
    if session.current_task_id:
        task = db.get(GuideTask, session.current_task_id)
        if task and task.plan_json:
            plan = json.loads(task.plan_json)
            plan["validation_status"] = "stale_supply"
            task.plan_json = json.dumps(plan)
            # Rewriting the plan is a plan change like any other: it advances the
            # task version, so a turn that snapshotted the older plan (and may
            # still be waiting on a model call) is refused instead of committing
            # its stale plan over this invalidation.
            task.state_version += 1
            task.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"session_id": session_id, "session_version": session.session_version}


@router.post("/guide/tasks/{task_id}/plan-refresh", response_model=PlanRefreshResponse)
def refresh_plan(
    task_id: str,
    body: PlanRefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    task = db.get(GuideTask, task_id)
    if not task:
        raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
    session = db.get(GuideSession, task.session_id)
    entry = EntryContext(**json.loads(session.entry_context_json)) if session else EntryContext()
    svc = PlanRefreshService(db, owner_id, entry.store_id, entry.delivery_zone_id)
    result = svc.refresh(
        task_id,
        request_id=body.request_id,
        expected_session_version=body.expected_session_version,
        expected_state_version=body.expected_state_version,
        base_plan_id=body.base_plan_id,
        base_plan_version=body.base_plan_version,
    )
    return PlanRefreshResponse(**result)


@router.post("/guide/tasks/{task_id}/plan-revisions", response_model=PlanRevisionResponse)
def revise_plan(
    task_id: str,
    body: PlanRevisionRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    task = db.get(GuideTask, task_id)
    if not task:
        raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
    session = db.get(GuideSession, task.session_id)
    entry = EntryContext(**json.loads(session.entry_context_json)) if session else EntryContext()
    svc = PlanRevisionService(db, owner_id, entry.store_id, entry.delivery_zone_id)
    result = svc.revise(
        task_id,
        request_id=body.request_id,
        expected_session_version=body.expected_session_version,
        expected_state_version=body.expected_state_version,
        base_plan_id=body.base_plan_id,
        base_plan_version=body.base_plan_version,
        client_edit_sequence=body.client_edit_sequence,
        items=[i.model_dump() for i in body.items],
        coverage_intent=body.coverage_intent,
        user_supplied_ingredients=body.user_supplied_ingredients,
    )
    return PlanRevisionResponse(**result)


@router.post("/guide/tasks/{task_id}/confirm", response_model=ConfirmResponse)
def confirm_task(
    task_id: str,
    body: ConfirmRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    owner_id = _owner(request, response, db)
    digest = CartService.digest_request(body.model_dump())
    svc = ConfirmationService(db, owner_id)
    result = svc.confirm(
        task_id=task_id,
        plan_id=body.plan_id,
        plan_version=body.plan_version,
        expected_state_version=body.expected_state_version,
        selected_items=body.selected_items,
        idempotency_key=idempotency_key,
        request_digest=digest,
        expected_session_version=body.expected_session_version,
    )
    session = db.get(GuideSession, db.get(GuideTask, task_id).session_id)
    result["session_version"] = session.session_version if session else 0
    return ConfirmResponse(**result)


@router.post(
    "/guide/tasks/{task_id}/items/{sku_id}/add",
    response_model=AddPlanItemResponse,
)
def add_plan_item(
    task_id: str,
    sku_id: str,
    body: AddPlanItemRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Explicit per-row cart write from an editable plan.

    Every check the batch confirm performs still applies; the row is recorded as
    added so the later batch confirm cannot buy it twice.
    """
    owner_id = _owner(request, response, db)
    task = db.get(GuideTask, task_id)
    if not task:
        raise AppError(403, "SESSION_FORBIDDEN", "Task not found")
    session = db.get(GuideSession, task.session_id)
    entry = EntryContext(**json.loads(session.entry_context_json)) if session else EntryContext()
    svc = PlanItemService(db, owner_id, entry.store_id, entry.delivery_zone_id)
    result = svc.add_item(
        task_id,
        sku_id=sku_id,
        quantity=body.quantity,
        request_id=idempotency_key or body.request_id,
        expected_state_version=body.expected_state_version,
        expected_session_version=body.expected_session_version,
    )
    return AddPlanItemResponse(**result)


@router.post("/guide/tasks/{task_id}/cancel", response_model=CancelResponse)
def cancel_task(
    task_id: str,
    body: CancelRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    owner_id = _owner(request, response, db)
    request_id = idempotency_key or body.request_id
    digest = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    svc = TaskLifecycleService(db, owner_id)
    return CancelResponse(**svc.cancel_task(
        task_id,
        request_id=request_id,
        expected_session_version=body.expected_session_version,
        expected_state_version=body.expected_state_version,
        request_digest=digest,
    ))


@router.get("/guide/operations")
def get_operations(
    request: Request,
    response: Response,
    op_type: str = Query(...),
    request_id: str = Query(...),
    db: Session = Depends(get_db),
):
    owner_id = _owner(request, response, db)
    ops = (
        db.query(GuideOperation)
        .filter_by(owner_id=owner_id, op_type=op_type, request_id=request_id)
        .filter(GuideOperation.op_type != "turn_stream")
        .all()
    )
    operations = [
        {
            "operation_id": op.operation_id,
            "op_type": op.op_type,
            "scope_id": op.scope_id,
            "status": op.status,
            "result": json.loads(op.result_json) if op.result_json else None,
        }
        for op in ops
    ]
    if not operations and op_type == "confirm":
        cart_ops = (
            db.query(CartOperation)
            .filter_by(owner_id=owner_id, idempotency_key=request_id)
            .all()
        )
        operations = [
            {
                "operation_id": op.operation_id,
                "op_type": "confirm",
                "scope_id": op.task_id,
                "status": op.status,
                "result": json.loads(op.result_json) if op.result_json else None,
            }
            for op in cart_ops
        ]
    return {"operations": operations}


@router.post(
    "/guide/sessions/{session_id}/turns/stop",
    response_model=StopTurnResponse,
)
def stop_turn(
    session_id: str,
    body: StopTurnRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Cooperative server-side stop for the logical turn identified by request_id.

    This cancels generation only. A cart write that already committed, and a plan
    the user already confirmed, are never undone by stopping.
    """
    owner_id = _owner(request, response, db)
    svc = TurnStreamService(db, owner_id)
    return StopTurnResponse(**svc.request_stop(session_id, body.request_id))


@router.post("/guide/sessions/{session_id}/turns/stream")
async def process_turn_stream(
    session_id: str,
    body: TurnRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    from fastapi.responses import StreamingResponse

    owner_id = _owner(request, response, db)
    # Ownership must be rejected before the streaming response starts; an error
    # raised from inside the generator would arrive after the headers.
    session = db.get(GuideSession, session_id)
    if not session or session.owner_id != owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
    svc = TurnStreamService(db, owner_id)
    view_ctx = body.view_context.model_dump() if body.view_context else None

    async def event_generator():
        async for event in svc.stream_turn(
            session_id,
            body.message,
            body.request_id,
            body.expected_task_id,
            body.expected_state_version,
            body.expected_session_version,
            view_ctx,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        # ``no-transform`` matters: intermediaries (including Next.js's own
        # compression middleware) must not gzip a text/event-stream body, because
        # a gzip stream only flushes at close and would defeat incremental
        # delivery. Keep the payload opaque end to end.
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

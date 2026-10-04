"""Mercury customer service API endpoints."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from contextlib import closing

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette import EventSourceResponse

from app.core.database import get_db
from app.core.identity import get_or_create_owner

# 添加 Mercury 到 Python 路径
mercury_path = Path(__file__).resolve().parents[3] / "Mercury"
if str(mercury_path) not in sys.path:
    sys.path.insert(0, str(mercury_path))

from mercury.agent import run_mercury
from mercury.db import connect

DEMO_MERCURY_USER = "test_user_001"


def _owner(request: Request, response: Response, db: Session = Depends(get_db)) -> str:
    return get_or_create_owner(request, response, db)


def resolve_mercury_user_id(ceres_owner_id: str) -> str:
    """Ceres owner 与 Mercury 演示库用户对齐。"""
    with closing(connect()) as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (ceres_owner_id,)
        ).fetchone():
            return ceres_owner_id
        if conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (DEMO_MERCURY_USER,)
        ).fetchone():
            return DEMO_MERCURY_USER
    return ceres_owner_id

router = APIRouter(prefix="/api/v1/mercury", tags=["mercury"])


class TurnRequest(BaseModel):
    """Mercury turn request."""
    message: str
    request_id: str


class SessionResponse(BaseModel):
    """Mercury session response."""
    session_id: str
    created_at: str


@router.post("/sessions", response_model=SessionResponse)
async def create_mercury_session(owner_id: str = Depends(_owner)) -> dict[str, Any]:
    """创建 Mercury 客服会话."""
    session_id = f"ms_{uuid.uuid4().hex[:12]}"
    return {
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat()
    }


@router.post("/sessions/{session_id}/turns/stream")
async def mercury_turn_stream(
    session_id: str,
    request: TurnRequest,
    owner_id: str = Depends(_owner)
):
    """发送消息给墨墨,返回 SSE 流式响应."""
    message = request.message

    async def event_generator():
        # 1. 发送接受事件
        yield {
            "event": "accepted",
            "data": json.dumps({"request_id": request.request_id})
        }

        try:
            # 2. 调用 Mercury (同步调用)
            # 在生产环境中,应该使用 asyncio.to_thread 或异步包装
            mercury_uid = resolve_mercury_user_id(owner_id)
            response_text = await asyncio.to_thread(
                run_mercury, mercury_uid, message
            )

            # 3. 分块发送以模拟流式输出（中文按字符，英文尽量按词）
            chunk_size = 2
            i = 0
            text = response_text
            while i < len(text):
                end = i + chunk_size
                if end < len(text) and text[end - 1].isascii() and text[end].isascii():
                    while end < len(text) and end - i < 12 and text[end - 1].isascii() and text[end] != " ":
                        end += 1
                    while end < len(text) and text[end] == " ":
                        end += 1
                piece = text[i:end]
                yield {
                    "event": "answer.delta",
                    "data": json.dumps({"text": piece}),
                }
                await asyncio.sleep(0.03)
                i = end

            # 4. 发送完成事件
            yield {
                "event": "turn.completed",
                "data": json.dumps({
                    "session_id": session_id,
                    "final_text": response_text
                })
            }
        except Exception as e:
            # 5. 错误处理
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)})
            }

    return EventSourceResponse(event_generator())

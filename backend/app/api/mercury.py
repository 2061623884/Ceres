"""Mercury customer service API endpoints."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from app.api.bootstrap import _owner

# 添加 Mercury 到 Python 路径
mercury_path = Path(__file__).resolve().parents[4] / "Mercury"
if str(mercury_path) not in sys.path:
    sys.path.insert(0, str(mercury_path))

from mercury.agent import run_mercury

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
            response_text = run_mercury(user_id=owner_id, message=message)

            # 3. 分块发送以模拟流式输出(打字机效果)
            words = response_text.split()
            for word in words:
                yield {
                    "event": "answer.delta",
                    "data": json.dumps({"text": word + " "})
                }
                await asyncio.sleep(0.03)  # 30ms 延迟营造打字机效果

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

"""Call-level diagnostics survive errors without holding a model-time write lock."""
import json
import uuid

import pytest
from sqlalchemy import text

from app.llm.errors import LLMProviderError
from app.models.trace import TraceEvent
from support import create_session, post_turn


@pytest.mark.parametrize("fail_on", [1, 2])
def test_timeout_identifies_the_exact_call_and_stage(client, semantic_provider, fail_on):
    from app.core.database import SessionLocal

    count = 0

    def propose(request):
        nonlocal count
        count += 1
        # An independent SQLite writer must be able to run while the model is
        # in flight. This fails if a trace flush left a write transaction open.
        with SessionLocal() as other:
            other.execute(text("PRAGMA busy_timeout=100"))
            other.execute(text("BEGIN IMMEDIATE"))
            other.rollback()
        if count == fail_on:
            raise LLMProviderError("MODEL_TIMEOUT", "private upstream detail", retryable=True)
        return {"target": {"kind": "meal", "name": "可乐鸡翅", "intent": "explore"},
                "lookups": [{"kind": "dish", "query": "可乐鸡翅"}]}

    semantic_provider([propose, propose])
    sid = create_session(client)
    response = post_turn(client, sid, "我想吃可乐鸡翅", None, request_id=str(uuid.uuid4()))
    assert response.status_code == 200, response.text
    assert response.json()["plan_effect"] == "keep"
    assert any(row.get("code") == "MODEL_TIMEOUT" for row in response.json()["action_results"])
    with SessionLocal() as db:
        events = db.query(TraceEvent).filter_by(session_id=sid).all()
        started = [e for e in events if e.phase == "model_call_started"]
        failed = [e for e in events if e.phase == "model_call_failed"]
        completed = [e for e in events if e.phase == "model_call_completed"]
        assert len(started) == fail_on
        assert len(completed) == fail_on - 1
        assert len(failed) == 1
        detail = json.loads(failed[0].output_summary)
        assert detail["call_number"] == fail_on
        assert detail["stage"] == ("understanding" if fail_on == 1 else "answer")
        assert detail["read_result_count"] == fail_on - 1
        assert failed[0].duration_ms >= 0
        assert failed[0].error == "MODEL_TIMEOUT"
        assert "private upstream detail" not in failed[0].output_summary
        assert "可乐鸡翅" not in failed[0].output_summary
    assert client.get('/api/v1/cart').json()['items'] == []


def test_understanding_timeout_is_reported_as_timeout_and_keeps_existing_plan(
    client, semantic_provider
):
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan"),
            LLMProviderError("MODEL_TIMEOUT", "Model request timed out", retryable=True),
        ]
    )
    sid = create_session(client)
    first = post_turn(client, sid, "我想吃番茄炒蛋")
    assert first.status_code == 200, first.text
    plan_before = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert plan_before is not None

    response = post_turn(client, sid, "再给我看看鸡蛋", first.json())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == "抱歉，这次响应超时了，请稍后重试。"
    assert body["plan_effect"] == "keep"
    assert body["action_results"] == [{
        "type": "understanding_failed",
        "status": "failed",
        "saved": False,
        "reply_ok": False,
        "code": "MODEL_TIMEOUT",
        "message": "Model request timed out",
        "retryable": True,
        "action_id": "a1",
    }]
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] == plan_before
    assert client.get("/api/v1/cart").json()["items"] == []


def test_protocol_provider_failure_refuses_without_repair(client, semantic_provider):
    from app.core.database import SessionLocal

    provider = semantic_provider([
        LLMProviderError("EMPTY_MODEL_RESPONSE", "empty", retryable=True),
        {"reply": "你好"},
    ])
    sid = create_session(client)
    response = post_turn(client, sid, "你好")
    assert response.status_code == 200, response.text
    assert response.json()["route"] == "refuse"
    assert response.json()["message"] == (
        "抱歉，这一轮我没能理解清楚（EMPTY_MODEL_RESPONSE）：empty "
        "请换个说法，或直接说想吃什么、想买什么。"
    )
    assert provider.remaining() == 1
    with SessionLocal() as db:
        event = db.query(TraceEvent).filter_by(
            session_id=sid, phase="model_call_failed").one()
        detail = json.loads(event.output_summary)
        assert detail["call_number"] == 1
        assert detail["repair"] is False
        assert detail["stage"] == "understanding"

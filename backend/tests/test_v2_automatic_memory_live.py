"""Opt-in ticket 06 samples against the explicitly configured real models."""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from support import create_session, send_turn
from support.v2_fixture import source_database_path


pytestmark = pytest.mark.skipif(
    os.environ.get("CERES_LIVE_MEMORY_ACCEPTANCE") != "1",
    reason="real-model ticket 06 acceptance is explicitly invoked",
)


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("case", ["stable", "temporary", "explicit-conflict"])
def test_real_reply_and_background_extraction(client, run, case):
    from app.agent.protocol import MemoryAction
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.models.trace import TraceEvent
    from app.services.memory_service import MemoryService

    settings = get_settings()
    assert settings.llm_mode == "live" and settings.memory_model
    sid = create_session(client)
    owner = client.cookies.get("sg_owner_id")
    if case == "explicit-conflict":
        with SessionLocal() as db:
            MemoryService(db, owner).execute(MemoryAction(
                verb="save", category="user", content="平时只喜欢百事可乐，不喜欢可口可乐",
            ))
            db.commit()
    message = {
        "stable": "平时饮料我更喜欢百事可乐，这是我的长期习惯，今天不用采购。",
        "temporary": "只讨论今天：4个人，预算60元，今天不用采购，这些条件不代表我长期习惯。",
        "explicit-conflict": "我平时只喜欢可口可乐，今天不用采购。",
    }[case]
    request_id = f"live-memory-{case}-{run}"
    start = time.monotonic()
    result = send_turn(client, sid, message, request_id=request_id)
    reply_seconds = time.monotonic() - start
    print(json.dumps({"case": case, "run": run, "reply_seconds": round(reply_seconds, 3),
                      "reply": result["message"], "action_results": result["action_results"]}, ensure_ascii=False))
    assert result["answer_status"] == "accepted"
    assert not any(row["type"] == "memory" for row in result["action_results"])
    deadline = time.monotonic() + settings.llm_timeout + 5
    terminal = None
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            terminal = db.query(TraceEvent).filter(
                TraceEvent.owner_id == owner, TraceEvent.request_id == request_id,
                TraceEvent.phase.in_(("memory_extract_completed", "memory_background_failed")),
            ).first()
            if terminal is not None:
                records = [row.to_dict() for row in MemoryService(db, owner).list_valid()]
                break
        time.sleep(0.05)
    assert terminal is not None, "background model did not finish within its configured timeout"
    print(json.dumps({
        "case": case, "run": run, "model": settings.llm_model,
        "memory_model": settings.memory_model, "base_url": settings.openai_base_url,
        "reply_seconds": round(reply_seconds, 3), "reply": result["message"],
        "memory_phase": terminal.phase, "memory_error": terminal.error, "records": records,
    }, ensure_ascii=False))
    assert terminal.phase == "memory_extract_completed", terminal.output_summary
    assert reply_seconds <= 15
    if case == "stable":
        assert records and all(row["source"] == "automatic" for row in records)
        assert any("百事" in row["content"] for row in records)
        assert all(row["expires_at"] is not None for row in records)
    elif case == "temporary":
        assert records == []
    else:
        assert len(records) == 1 and records[0]["source"] == "explicit"
        assert records[0]["content"] == "平时只喜欢百事可乐，不喜欢可口可乐"
        assert records[0]["expires_at"] is None


@pytest.mark.parametrize("run", [1, 2])
def test_real_dream_preserves_explicit_and_cleans_automatic(client, run):
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.models.memory import ShoppingMemory
    from app.models.trace import TraceEvent
    from app.services.automatic_memory_service import AutomaticMemoryService
    from app.services.memory_service import MemoryService

    create_session(client)
    owner = client.cookies.get("sg_owner_id")
    settings = get_settings()
    contents = [
        ("feedback", "推荐前先说明理由"), ("feedback", "推荐前先说明理由"),
        ("feedback", "推荐时请先展示价格再展示规格"), ("user", "平时喜欢无糖饮料"),
        ("project", "每周五采购周末食材"), ("reference", "历史采购方案ID是plan-memory-demo-06"),
        ("user", "偏好小包装零食"), ("feedback", "商品比较时说明每升单价"),
        ("project", "家中备有食用盐"), ("reference", "常用门店ID为store-demo-01"),
    ]
    with SessionLocal() as db:
        for i, (category, content) in enumerate(contents):
            db.add(ShoppingMemory(memory_id=f"auto-{i}", owner_id=owner, category=category,
                source="automatic", content=content, expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        db.add(ShoppingMemory(memory_id="explicit", owner_id=owner, category="user",
            source="explicit", content="平时只喜欢百事可乐"))
        db.add(ShoppingMemory(memory_id="expired", owner_id=owner, category="project", source="automatic",
            content="过时采购背景", expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
        db.commit()
        start = time.monotonic()
        assert AutomaticMemoryService(db, owner).dream_if_due(trace_id=f"live-dream-{run}") is True
        seconds = time.monotonic() - start
        records = [row.to_dict() for row in MemoryService(db, owner).list_valid()]
        print(json.dumps({"case": "dream", "run": run, "memory_model": settings.memory_model,
                          "dream_seconds": round(seconds, 3), "records": records}, ensure_ascii=False))
        automatic = [row for row in records if row["source"] == "automatic"]
        assert automatic and sum(row["content"] == "推荐前先说明理由" for row in automatic) <= 1
        assert db.get(ShoppingMemory, "expired") is None
        explicit = db.get(ShoppingMemory, "explicit")
        assert explicit.content == "平时只喜欢百事可乐" and explicit.expires_at is None
        assert db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_dream_completed").count() == 1
        assert AutomaticMemoryService(db, owner).dream_if_due(trace_id="too-soon") is False

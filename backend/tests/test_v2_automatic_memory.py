"""Background extraction is tested at the external model and Guide boundaries."""

import json
import threading
import time

import pytest

from support import create_session, send_turn
from support.v2_fixture import source_database_path


@pytest.mark.parametrize("run", [1, 2])
def test_reply_finishes_while_memory_model_is_pending(client, semantic_provider, monkeypatch, run):
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.openai_transport import OpenAICompatTransport
    from app.services.memory_service import MemoryService

    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def post_json(self, payload, **kwargs):
        assert payload["model"] == "test-memory-model"
        calls.append(payload["model"])
        entered.set()
        assert release.wait(5), "test must release the isolated memory provider"
        return {"choices": [{"message": {"content": json.dumps({"memories": [
            {"category": "user", "content": "平时喜欢百事可乐", "conflicts_with": []},
        ]}, ensure_ascii=False)}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    semantic_provider([{"reply": "明白，推荐时会先说明理由。"}])
    sid = create_session(client)
    try:
        reply = send_turn(client, sid, "我平时喜欢百事可乐", request_id=f"memory-pending-{run}")
        assert reply["answer_status"] == "accepted"
        assert entered.wait(1), "normal chat did not start background extraction"
        assert not release.is_set(), "final reply must not wait for the memory model"
        replayed = send_turn(client, sid, "我平时喜欢百事可乐", request_id=f"memory-pending-{run}")
        assert replayed["assistant_message_id"] == reply["assistant_message_id"]
        time.sleep(0.05)
        assert calls == ["test-memory-model"], "receipt replay must not start another background model call"
    finally:
        release.set()
    owner = client.cookies.get("sg_owner_id")
    deadline = time.monotonic() + 3
    records = []
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            records = MemoryService(db, owner).list_valid()
            if records:
                break
        time.sleep(0.02)
    assert len(records) == 1 and records[0].source == "automatic"
    assert records[0].expires_at is not None


@pytest.mark.parametrize("run", [1, 2])
def test_automatic_expiry_deduplication_and_explicit_conflict(client, semantic_provider, monkeypatch, run):
    from datetime import datetime, timezone
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.openai_transport import OpenAICompatTransport
    from app.services.automatic_memory_service import AutomaticMemoryService
    from app.services.memory_service import MemoryService

    semantic_provider([{"memory": {"verb": "save", "category": "user", "content": "平时喜欢百事可乐"}}])
    sid = create_session(client)
    saved = send_turn(client, sid, "请记住平时喜欢百事可乐")
    explicit = next(row for row in saved["action_results"] if row["type"] == "memory")["records"][0]
    owner = client.cookies.get("sg_owner_id")
    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()

    def post_json(self, payload, **kwargs):
        return {"choices": [{"message": {"content": json.dumps({"memories": [
            {"category": "user", "content": "喜欢可口可乐", "conflicts_with": [explicit["ref"]]},
            {"category": "feedback", "content": "推荐前先给出理由"},
            {"category": "feedback", "content": "推荐前先给出理由"},
        ]}, ensure_ascii=False)}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    for request_id in ("extract-one", "extract-two"):
        with SessionLocal() as db:
            AutomaticMemoryService(db, owner).process_turn(session_id=sid, request_id=request_id,
                trace_id=f"trace-{request_id}", message="以后推荐前先给理由", reply="好的。")
    with SessionLocal() as db:
        records = MemoryService(db, owner).list_valid()
        assert len(records) == 2
        assert next(row for row in records if row.source == "explicit").to_dict() == explicit
        automatic = next(row for row in records if row.source == "automatic")
        remaining = automatic.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        assert 29.99 < remaining.total_seconds() / 86400 <= 30
        expiry = automatic.expires_at
    with SessionLocal() as db:
        AutomaticMemoryService(db, owner).process_turn(session_id=sid, request_id="extract-two",
            trace_id="trace-replay", message="同一回合重放", reply="好的。")
        assert next(row for row in MemoryService(db, owner).list_valid() if row.source == "automatic").expires_at == expiry


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("model, code", [("", "MEMORY_MODEL_MISSING"), ("test-memory-model", "MODEL_TIMEOUT")])
def test_background_failure_is_recorded_without_changing_reply(client, semantic_provider, monkeypatch, run, model, code):
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.errors import LLMProviderError
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.trace import TraceEvent
    from app.services.memory_service import MemoryService

    monkeypatch.setenv("MEMORY_MODEL", model)
    get_settings.cache_clear()
    calls = []

    def post_json(self, payload, **kwargs):
        calls.append(payload["model"])
        raise LLMProviderError("MODEL_TIMEOUT", "isolated memory timeout", retryable=True)

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    semantic_provider([{"reply": "今天的预算只用于本次采购。"}])
    sid = create_session(client)
    result = send_turn(client, sid, "今天4个人，预算60元，仅这一次", request_id=f"failed-memory-{run}")
    assert result["answer_status"] == "accepted" and result["message"] == "今天的预算只用于本次采购。"
    owner = client.cookies.get("sg_owner_id")
    deadline = time.monotonic() + 3
    failure = None
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            failure = db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_background_failed").first()
            if failure is not None:
                assert MemoryService(db, owner).list_valid() == []
                break
        time.sleep(0.02)
    assert failure is not None and failure.error == code
    replayed = send_turn(client, sid, "今天4个人，预算60元，仅这一次", request_id=f"failed-memory-{run}")
    assert replayed["assistant_message_id"] == result["assistant_message_id"]
    time.sleep(0.05)
    assert calls == ([model] if model else [])
    with SessionLocal() as db:
        assert db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_background_failed").count() == 1


@pytest.mark.parametrize("run", [1, 2])
def test_dream_threshold_interval_deduplication_and_expired_cleanup(client, monkeypatch, run):
    from datetime import datetime, timedelta, timezone
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.memory import ShoppingMemory
    from app.models.trace import TraceEvent
    from app.services.automatic_memory_service import AutomaticMemoryService
    from app.services.memory_service import MemoryService

    create_session(client)
    owner = client.cookies.get("sg_owner_id")
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()

    def post_json(self, payload, **kwargs):
        assert json.loads(payload["messages"][-1]["content"])["mode"] == "dream"
        return {"choices": [{"message": {"content": json.dumps({"memories": [
            {"category": "feedback", "content": "先讲理由"},
        ], "drop_refs": ["auto-1"]}, ensure_ascii=False)}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    with SessionLocal() as db:
        for i in range(9):
            db.add(ShoppingMemory(memory_id=f"auto-{i}", owner_id=owner, category="feedback", source="automatic",
                content="先讲理由" if i < 2 else f"持续纠正{i}", expires_at=now + timedelta(days=30)))
        db.add(ShoppingMemory(memory_id="explicit", owner_id=owner, category="user", source="explicit", content="喜欢百事可乐"))
        db.add(ShoppingMemory(memory_id="expired", owner_id=owner, category="project", source="automatic", content="旧采购背景", expires_at=now - timedelta(days=1)))
        db.add(ShoppingMemory(memory_id="other-owner-expired", owner_id="other-owner", category="project", source="automatic", content="别人的旧背景", expires_at=now - timedelta(days=1)))
        original_expiry = now + timedelta(days=5)
        db.commit()
        db.get(ShoppingMemory, "auto-0").expires_at = original_expiry
        db.commit()
        service = AutomaticMemoryService(db, owner)
        assert service.dream_if_due(trace_id="below-threshold") is False
        db.add(ShoppingMemory(memory_id="auto-9", owner_id=owner, category="feedback", source="automatic", content="持续纠正9", expires_at=now + timedelta(days=30)))
        db.add(TraceEvent(event_id="prior-dream", trace_id="prior", owner_id=owner, phase="memory_dream_completed", created_at=now - timedelta(hours=23)))
        db.commit()
        assert service.dream_if_due(trace_id="too-soon") is False
        db.get(TraceEvent, "prior-dream").created_at = now - timedelta(hours=25)
        db.commit()
        assert service.dream_if_due(trace_id="due") is True
        records = MemoryService(db, owner).list_valid()
        assert len([row for row in records if row.source == "automatic"]) == 9
        assert db.get(ShoppingMemory, "auto-1") is None and db.get(ShoppingMemory, "expired") is None
        assert db.get(ShoppingMemory, "explicit").content == "喜欢百事可乐"
        assert db.get(ShoppingMemory, "auto-0").expires_at.replace(tzinfo=timezone.utc) == original_expiry
        assert db.get(ShoppingMemory, "other-owner-expired") is not None
        db.add(ShoppingMemory(memory_id="auto-new", owner_id=owner, category="feedback", source="automatic", content="新的持续纠正", expires_at=now + timedelta(days=30)))
        db.commit()
        assert service.dream_if_due(trace_id="just-completed") is False


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("forbidden_ref", ["explicit", "other-owner"])
def test_dream_refuses_explicit_and_other_owner_deletion(client, monkeypatch, run, forbidden_ref):
    from datetime import datetime, timedelta, timezone
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.core.errors import AppError
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.memory import ShoppingMemory
    from app.services.automatic_memory_service import AutomaticMemoryService

    create_session(client)
    owner = client.cookies.get("sg_owner_id")
    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()

    def post_json(self, payload, **kwargs):
        return {"choices": [{"message": {"content": json.dumps({"memories": [], "drop_refs": [forbidden_ref]})}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    with SessionLocal() as db:
        for i in range(10):
            db.add(ShoppingMemory(memory_id=f"auto-{i}", owner_id=owner, category="feedback", source="automatic", content=f"纠正{i}", expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        db.add(ShoppingMemory(memory_id="explicit", owner_id=owner, category="user", source="explicit", content="偏好百事"))
        db.add(ShoppingMemory(memory_id="other-owner", owner_id="another-owner", category="user", source="automatic", content="别人偏好", expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        db.commit()
        with pytest.raises(AppError) as error:
            AutomaticMemoryService(db, owner).dream_if_due(trace_id="invalid-dream")
        assert error.value.detail["error"]["code"] == "INVALID_MEMORY_OUTPUT"
        assert db.get(ShoppingMemory, forbidden_ref) is not None


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("mode", ["extract", "dream"])
def test_user_correction_during_model_call_stays_explicit(client, monkeypatch, run, mode):
    from datetime import datetime, timedelta, timezone
    from app.agent.protocol import MemoryAction
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.core.errors import AppError
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.memory import ShoppingMemory
    from app.services.automatic_memory_service import AutomaticMemoryService
    from app.services.memory_service import MemoryService

    sid = create_session(client)
    owner = client.cookies.get("sg_owner_id")
    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()
    with SessionLocal() as db:
        for i in range(10):
            db.add(ShoppingMemory(memory_id=f"auto-{i}", owner_id=owner, category="feedback",
                source="automatic", content=f"原始纠正{i}", expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        db.commit()

    def post_json(self, payload, **kwargs):
        # The user edits through the real service while the model owns an old
        # context. Its result must not delete/expire that now-explicit record.
        with SessionLocal() as other_db:
            MemoryService(other_db, owner).execute(MemoryAction(verb="update", ref="auto-1", content="原始纠正1"))
            other_db.commit()
        output = {"memories": [{"category": "feedback", "content": "原始纠正1"}]} if mode == "extract" else {"memories": [], "drop_refs": ["auto-1"]}
        return {"choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    with SessionLocal() as db:
        service = AutomaticMemoryService(db, owner)
        if mode == "extract":
            service.process_turn(session_id=sid, request_id="correction-during-extract", trace_id="extract",
                                 message="以后先讲理由", reply="好的。")
        else:
            with pytest.raises(AppError):
                service.dream_if_due(trace_id="dream")
    with SessionLocal() as db:
        corrected = db.get(ShoppingMemory, "auto-1")
        assert corrected is not None and corrected.source == "explicit" and corrected.expires_at is None


@pytest.mark.parametrize("run", [1, 2])
def test_dream_failure_preserves_committed_extraction(client, monkeypatch, run):
    from datetime import datetime, timedelta, timezone
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.errors import LLMProviderError
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.memory import ShoppingMemory
    from app.models.trace import TraceEvent
    from app.services.automatic_memory_service import AutomaticMemoryService
    from app.services.memory_service import MemoryService

    sid = create_session(client)
    owner = client.cookies.get("sg_owner_id")
    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()
    calls = []

    def post_json(self, payload, **kwargs):
        mode = json.loads(payload["messages"][-1]["content"])["mode"]
        calls.append(mode)
        if mode == "dream":
            raise LLMProviderError("MODEL_TIMEOUT", "isolated Dream timeout", retryable=True)
        return {"choices": [{"message": {"content": json.dumps({"memories": [
            {"category": "feedback", "content": "以后推荐先说明理由"},
        ]}, ensure_ascii=False)}}]}

    monkeypatch.setattr(OpenAICompatTransport, "post_json", post_json)
    with SessionLocal() as db:
        for i in range(9):
            db.add(ShoppingMemory(memory_id=f"auto-{i}", owner_id=owner, category="feedback",
                source="automatic", content=f"持续纠正{i}", expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        db.add(ShoppingMemory(memory_id="explicit", owner_id=owner, category="user", source="explicit", content="偏好百事"))
        db.commit()
        AutomaticMemoryService(db, owner).process_turn(session_id=sid, request_id="dream-failure",
            trace_id="dream-failure", message="以后推荐先说明理由", reply="好的。")
    with SessionLocal() as db:
        records = MemoryService(db, owner).list_valid()
        assert len([row for row in records if row.source == "automatic"]) == 10
        assert any(row.content == "以后推荐先说明理由" for row in records)
        assert db.get(ShoppingMemory, "explicit").expires_at is None
        assert db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_extract_completed").count() == 1
        assert db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_dream_completed").count() == 0
        failure = db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_background_failed").one()
        assert failure.error == "MODEL_TIMEOUT" and "isolated Dream timeout" in failure.output_summary
    assert calls == ["extract", "dream"]


@pytest.mark.parametrize("run", [1, 2])
def test_memory_provider_requires_explicit_memories(monkeypatch, run):
    from app.core.config import get_settings
    from app.llm.errors import LLMProviderError
    from app.llm.memory_provider import MemoryProvider
    from app.llm.openai_transport import OpenAICompatTransport

    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()
    monkeypatch.setattr(OpenAICompatTransport, "post_json", lambda self, payload, **kwargs:
                        {"choices": [{"message": {"content": "{}"}}]})
    with pytest.raises(LLMProviderError) as error:
        MemoryProvider().complete("extract", {"message": "今天预算60元", "reply": "好的。", "memories": []})
    assert error.value.code == "INVALID_MEMORY_OUTPUT"


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("response", [
    {"choices": []},
    {"choices": [{}]},
    {"choices": [{"message": {}}]},
    {"choices": [{"message": {"content": None}}]},
], ids=["empty-choices", "missing-message", "missing-content", "nontext-content"])
def test_background_records_invalid_response_envelope(client, semantic_provider, monkeypatch, run, response):
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.llm.openai_transport import OpenAICompatTransport
    from app.models.trace import TraceEvent
    from app.services.memory_service import MemoryService

    monkeypatch.setenv("MEMORY_MODEL", "test-memory-model")
    get_settings.cache_clear()
    monkeypatch.setattr(OpenAICompatTransport, "post_json", lambda self, payload, **kwargs: response)
    semantic_provider([{"reply": "好的，今天不采购。"}])
    sid = create_session(client)
    result = send_turn(client, sid, "今天不采购", request_id=f"invalid-envelope-{run}")
    assert result["answer_status"] == "accepted" and result["message"] == "好的，今天不采购。"
    owner = client.cookies.get("sg_owner_id")
    deadline = time.monotonic() + 3
    failure = None
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            failure = db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_background_failed").first()
            if failure is not None:
                assert MemoryService(db, owner).list_valid() == []
                assert db.query(TraceEvent).filter_by(owner_id=owner, phase="memory_extract_completed").count() == 0
                break
        time.sleep(0.02)
    assert failure is not None and failure.error == "INVALID_MEMORY_OUTPUT"
    assert failure.output_summary

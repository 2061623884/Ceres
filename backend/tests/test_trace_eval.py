"""O05 trace and eval fault-injection tests."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
import pytest

from app.models.trace import TraceEvent
from app.evaluation.runner import EvalConfigError, load_cases, parse_args, validate_case_config
from support import post_turn


def test_workflow_records_multiple_trace_events(client):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]
    body = {
        "request_id": str(uuid.uuid4()),
        "message": "我想吃番茄炒蛋",
        "expected_task_id": None,
        "expected_state_version": 0,
    }
    resp = post_turn(client, sid, body["message"], None, request_id=body["request_id"])
    assert resp.status_code == 200
    trace_id = resp.json()["trace_id"]

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        events = db.query(TraceEvent).filter_by(trace_id=trace_id).all()
        assert len(events) >= 2
        phases = {e.phase for e in events}
        assert "understanding" in phases
        # The turn's result is traced too — at the shared pre-commit call point,
        # i.e. after the model and the executor returned, not before the model call.
        assert "turn_result" in phases, phases
        result = next(e for e in events if e.phase == "turn_result")
        assert result.session_id == sid
        assert result.request_id == body["request_id"]
        assert result.task_id == resp.json()["task_id"]
        summary = json.loads(result.output_summary)
        assert summary["status"] == resp.json()["status"]
        assert summary["plan_effect"] == resp.json()["plan_effect"]
        # Facts only — the shopper's text never reaches the summary.
        assert body["message"] not in result.output_summary
    finally:
        db.close()

    # A replay is served from the stored response: no second model call, and no
    # second trace record either.
    replay = post_turn(
        client, sid, body["message"], None, request_id=body["request_id"]
    )
    assert replay.status_code == 200
    assert replay.json()["trace_id"] == trace_id

    db = SessionLocal()
    try:
        after = db.query(TraceEvent).filter_by(trace_id=trace_id).count()
        assert after == len(events), "a replayed turn recorded extra trace events"
    finally:
        db.close()


def test_badcase_create_commits(client):
    from app.core.config import get_settings

    token = get_settings().internal_admin_token or "dev-internal-token"
    trace_id = "trace-test-bc"
    resp = client.post(
        "/api/v1/internal/badcases",
        headers={"X-Internal-Token": token},
        json={
            "trace_id": trace_id,
            "category": "confirm",
            "expected_behavior": "200",
            "actual_behavior": "500",
        },
    )
    if resp.status_code == 403:
        return
    assert resp.status_code == 200

    from app.core.database import SessionLocal
    from app.models.trace import Badcase

    db = SessionLocal()
    try:
        bc = db.query(Badcase).filter_by(trace_id=trace_id).first()
        assert bc is not None
    finally:
        db.close()


def test_eval_fails_when_confirm_broken(client, monkeypatch):
    """Fault injection: broken confirm must make eval case with cart check fail."""
    from app.evaluation.runner import run_case

    case = {
        "case_id": "fault-confirm",
        "turns": [{"message": "我想吃番茄炒蛋"}],
        "confirm_plan": True,
        "check_cart": True,
        "expected_actions": [{"type": "cart_has_sku", "sku_id": "demo:tomato-fresh-500g"}],
    }
    real_post = client.post
    confirms = []

    def post(url, *args, **kwargs):
        if "/confirm" in url:
            confirms.append((url, kwargs))
            class FakeResp:
                status_code = 500

            return FakeResp()
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(client, "post", post)
    result = run_case(client, case)
    assert len(confirms) == 1, result
    assert result["turn_states"][0]["plan"]
    assert result["passed"] is False
    assert any("confirm" in f for f in result["failures"])


def test_eval_sse_plan_confirm_and_cart(client, monkeypatch):
    from app.evaluation.runner import run_case

    real_post = client.post
    real_stream = client.stream
    requests = []
    confirms = []

    def stream(method, url, **kwargs):
        requests.append((method, url, kwargs["json"]))
        return real_stream(method, url, **kwargs)

    def post(url, *args, **kwargs):
        if "/confirm" in url:
            confirms.append(kwargs["json"])
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(client, "stream", stream)
    monkeypatch.setattr(client, "post", post)
    result = run_case(client, {
        "case_id": "sse-plan-confirm",
        "turns": [{"message": "我想吃番茄炒蛋"}],
        "confirm_plan": True,
        "check_cart": True,
        "expected_actions": [
            "has_plan",
            {"type": "cart_has_sku", "sku_id": "demo:tomato-fresh-500g"},
        ],
    })
    assert result["passed"], result
    assert len(result["turn_states"]) == 1
    assert len(requests) == 1
    assert requests[0][0] == "POST"
    assert requests[0][1].endswith("/turns/stream")
    assert len(confirms) == 1
    assert confirms[0]["plan_id"] == result["turn_states"][0]["plan"]["plan_id"]


def test_eval_sse_multiturn_forwards_versions(client, monkeypatch):
    from app.evaluation.runner import run_case

    real_stream = client.stream
    bodies = []

    def stream(method, url, **kwargs):
        assert method == "POST" and url.endswith("/turns/stream")
        bodies.append(kwargs["json"])
        return real_stream(method, url, **kwargs)

    monkeypatch.setattr(client, "stream", stream)
    result = run_case(client, {
        "case_id": "sse-versions",
        "turns": [{"message": "我想吃番茄炒蛋"}, {"message": "改成3人份"}],
        "expected_actions": ["has_plan"],
    })
    assert result["passed"], result
    first, second = result["turn_states"]
    assert len(bodies) == 2
    assert bodies[0]["expected_task_id"] is None
    assert bodies[0]["expected_state_version"] == 0
    assert bodies[0]["expected_session_version"] == 0
    assert bodies[1]["expected_task_id"] == first["task_id"]
    assert bodies[1]["expected_state_version"] == first["state_version"]
    assert bodies[1]["expected_session_version"] == first["session_version"]
    assert second["task_id"] == first["task_id"]


def test_eval_checks_saved_plan_after_read_only_keep(client, semantic_provider):
    from app.evaluation.runner import run_case
    from support.semantic_agent import lookup_then_add, reply_only

    semantic_provider([*lookup_then_add("dish", "番茄炒蛋"), reply_only("好的。")])
    result = run_case(client, {
        "case_id": "read-only-keeps-saved-plan",
        "turns": [{"message": "我要番茄炒蛋"}, {"message": "谢谢"}],
        "expected_actions": [
            "has_plan",
            {"type": "turn_plan_unchanged", "turn": 2},
            {"type": "turn_plan_has_sku", "turn": 2, "sku_id": "demo:tomato-fresh-500g"},
        ],
    })
    assert result["passed"], result
    assert result["turn_responses"][1]["plan"] is None
    assert result["turn_responses"][1]["plan_effect"] == "keep"
    assert result["turn_states"][1]["plan"] == result["turn_states"][0]["plan"]


def test_eval_stops_after_timeout_in_a_completed_turn(client, semantic_provider):
    from app.evaluation.runner import run_case
    from app.llm.errors import LLMProviderError
    from support.semantic_agent import request_new

    provider = semantic_provider([
        LLMProviderError("MODEL_TIMEOUT", "Model request timed out", retryable=True),
        request_new("dish", "番茄炒蛋"),
    ])
    result = run_case(client, {
        "case_id": "timeout-before-dependent-feedback",
        "turns": [{"message": "我要番茄炒蛋"}, {"message": "自己做"}],
        "confirm_plan": True,
        "expected_actions": ["has_plan"],
    })
    assert result["passed"] is False
    assert "MODEL_TIMEOUT" in result["failures"][0]
    assert len(provider.requests) == 1
    assert len(result["turn_responses"]) == len(result["turn_states"]) == 1
    assert result["turn_responses"][0]["action_results"][0]["code"] == "MODEL_TIMEOUT"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_eval_preserves_cancel_clear_through_a_later_read_only_turn(client, semantic_provider):
    from app.evaluation.runner import run_case
    from support.semantic_agent import lookup_then_add, reply_only

    semantic_provider([
        *lookup_then_add("dish", "番茄炒蛋"),
        {"plan_act": "abandon"},
        reply_only("好的。"),
    ])
    result = run_case(client, {
        "case_id": "cancel-clears-visible-plan",
        "turns": [
            {"message": "我要番茄炒蛋"},
            {"message": "算了，不买了"},
            {"message": "谢谢"},
        ],
        "expected_actions": ["no_plan"],
        "check_cart": True,
    })
    assert result["passed"], result
    assert result["turn_responses"][1]["plan_effect"] == "clear"
    assert result["turn_responses"][1]["plan"] is None
    assert result["turn_states"][1]["plan"] is None
    assert result["turn_states"][2]["plan"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize(
    ("status", "events", "failure"),
    [
        (409, [], "status 409"),
        (200, [{"type": "error", "payload": {"code": "STALE_STATE", "message": "version mismatch"}}], "error STALE_STATE"),
        (200, [{"type": "turn.stopped", "payload": {"status": "stopped"}}], "stopped"),
        (200, [{"type": "accepted", "payload": {}}], "without turn.completed"),
    ],
)
def test_eval_sse_failure_never_confirms(client, monkeypatch, status, events, failure):
    from app.evaluation.runner import run_case

    real_post = client.post
    confirms = []

    def post(url, *args, **kwargs):
        if "/confirm" in url:
            confirms.append(url)
        return real_post(url, *args, **kwargs)

    @contextmanager
    def stream(method, url, **kwargs):
        assert method == "POST" and url.endswith("/turns/stream")
        yield SimpleNamespace(
            status_code=status,
            iter_lines=lambda: iter(f"data: {json.dumps(event)}" for event in events),
        )

    monkeypatch.setattr(client, "post", post)
    monkeypatch.setattr(client, "stream", stream)
    result = run_case(client, {
        "case_id": "sse-failure",
        "turns": [{"message": "我想吃番茄炒蛋"}],
        "confirm_plan": True,
        "expected_actions": ["has_plan"],
    })
    assert result["passed"] is False
    assert any(failure in item for item in result["failures"]), result
    assert result["turn_states"] == []
    assert confirms == []


def test_strong_eval_cases_have_assertions():
    cases = [c for c in load_cases() if c.get("case_id", "").startswith("strong-")]
    assert len(cases) >= 12
    for case in cases:
        validate_case_config(case)


def test_eval_rejects_empty_expected_actions():
    with pytest.raises(EvalConfigError):
        validate_case_config({"case_id": "x", "turns": [{"message": "hi"}], "expected_actions": []})


# ------------------------------------------------------------- runner CLI shape
#
# Argument parsing only: no test here calls ``main``, a model or the network.


def test_eval_cli_refuses_the_retired_mock_mode():
    with pytest.raises(SystemExit) as error:
        parse_args(["--mode", "mock"])
    assert error.value.code == 2


def test_eval_cli_requires_an_explicit_mode():
    with pytest.raises(SystemExit) as error:
        parse_args([])
    assert error.value.code == 2


def test_eval_cli_accepts_an_explicit_live_mode():
    assert parse_args(["--mode", "live"]).mode == "live"


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the reactive semantic provider, without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

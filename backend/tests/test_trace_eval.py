"""O05 trace and eval fault-injection tests."""

from __future__ import annotations

import json
import uuid
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

    def post(url, *args, **kwargs):
        if "/confirm" in url:
            class FakeResp:
                status_code = 500

            return FakeResp()
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(client, "post", post)
    result = run_case(client, case)
    assert result["passed"] is False
    assert any("confirm" in f for f in result["failures"])


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

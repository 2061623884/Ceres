"""M4 eval harness smoke test."""

from __future__ import annotations

from app.evaluation.runner import KNOWN_ACTIONS, load_cases, validate_case_config


def test_eval_cases_load():
    cases = load_cases()
    assert isinstance(cases, list)


def test_eval_known_actions():
    assert "has_plan" in KNOWN_ACTIONS
    assert "no_plan" in KNOWN_ACTIONS


def test_eval_config_validation():
    cases = [c for c in load_cases() if c.get("expected_actions")]
    for case in cases[:5]:
        validate_case_config(case)

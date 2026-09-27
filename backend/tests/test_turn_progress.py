"""Unit tests for TurnProgressSink contract."""

from __future__ import annotations

import pytest

from app.agent.turn_progress import NoOpTurnProgressSink, noop_progress_sink, validate_turn_phase


def test_noop_sink_accepts_frozen_phases():
    sink = noop_progress_sink()
    for phase in ("understanding", "retrieve", "validate"):
        sink.on_phase(phase)


def test_invalid_phase_rejected():
    with pytest.raises(ValueError, match="invalid turn phase"):
        validate_turn_phase("planning")


def test_noop_clarification_and_plan_ready_are_safe():
    sink = NoOpTurnProgressSink()
    sink.on_clarification({"question": "几个人？"})
    sink.on_plan_ready({"plan_id": "p1", "items": []})

"""Structured output parsing tests."""

import pytest

from app.llm.structured_output import extract_json_object


def test_extract_plain_json():
    data = extract_json_object('{"updates": {"people": 2}, "reply": "好的"}')
    assert data["updates"]["people"] == 2


def test_extract_fenced_json():
    raw = 'Here is the result:\n```json\n{"updates": {}, "reply": "你好"}\n```'
    data = extract_json_object(raw)
    assert data["reply"] == "你好"


def test_extract_invalid_raises():
    with pytest.raises(ValueError):
        extract_json_object("not json at all")

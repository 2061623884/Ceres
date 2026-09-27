"""Configuration tests."""

import os

from app.core.config import Settings, get_settings


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    get_settings.cache_clear()
    s = Settings()
    assert s.llm_mode == "live"


def test_no_secrets_in_health(client):
    resp = client.get("/health")
    text = resp.text.lower()
    assert "sk-" not in text
    assert "api_key" not in text

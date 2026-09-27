"""The live provider must report a failure, never fall back to a default.

The retired requirement-parser provider is gone; the same contract now belongs
to ``LiveSemanticProvider``, which is the only provider the runtime builds. These
tests inject a transport, so no network and no credentials are involved.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.llm.errors import LLMProviderError
from app.llm.live_semantic_provider import LiveSemanticProvider


def _settings() -> Settings:
    return Settings(
        llm_mode="live",
        openai_base_url="https://example.com/v1",
        openai_api_key="test-key",
        llm_model="test-model",
    )


class _Transport:
    """Returns whatever content the test hands it, or raises what it was given."""

    def __init__(self, content=None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    def post_json(self, payload, timeout_s=None):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.content}}]}


def _provider(transport: _Transport) -> LiveSemanticProvider:
    return LiveSemanticProvider(_settings(), transport=transport)


def test_output_that_is_not_json_is_reported_not_guessed():
    provider = _provider(_Transport(content="抱歉，我不能返回 JSON"))
    with pytest.raises(LLMProviderError) as exc:
        provider.propose({"user_message": "你好", "protocol": {}})
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_an_empty_completion_is_a_failure_not_an_empty_proposal():
    provider = _provider(_Transport(content="   "))
    with pytest.raises(LLMProviderError) as exc:
        provider.propose({"user_message": "你好", "protocol": {}})
    assert exc.value.code == "EMPTY_MODEL_RESPONSE"


def test_non_text_content_is_reported_as_invalid():
    provider = _provider(_Transport(content={"reply": "你好"}))
    with pytest.raises(LLMProviderError) as exc:
        provider.propose({"user_message": "你好", "protocol": {}})
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_a_transport_failure_propagates_unchanged():
    """A timeout is a timeout: it is never converted into a served answer."""
    failure = LLMProviderError("MODEL_TIMEOUT", "上游超时", retryable=True)
    provider = _provider(_Transport(error=failure))
    with pytest.raises(LLMProviderError) as exc:
        provider.propose({"user_message": "你好", "protocol": {}})
    assert exc.value.code == "MODEL_TIMEOUT"
    assert exc.value.retryable is True


def test_a_valid_proposal_is_returned_as_parsed_json():
    provider = _provider(_Transport(content='{"reply": "你好"}'))
    assert provider.propose({"user_message": "你好", "protocol": {}}) == {"reply": "你好"}

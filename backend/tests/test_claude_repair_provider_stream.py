"""Upstream transport evidence for the one provider, over real HTTP.

The retired tool-call provider streamed fragmented SSE with tool-call deltas. The
semantic provider is not a stream at all: it returns one JSON proposal per call,
so the transport evidence that matters is that a *real* HTTP round trip through
``httpx`` produces a parsed proposal, and that every upstream failure is reported
as itself.

These are protocol tests, not live-model evidence: the upstream is a local server,
no external provider is contacted, and the model's quality is not asserted here.
The turn-level consequences of a provider failure (SSE ``error``, stop, replay)
are covered by ``test_semantic_shared_contracts.py``.
"""

from __future__ import annotations

import pytest

from app.llm.errors import LLMProviderError
from support.sse_upstream import LocalUpstream, UpstreamScript, build_settings


@pytest.fixture()
def upstream():
    server = LocalUpstream([])
    try:
        yield server
    finally:
        server.close()


def _provider(upstream, scripts):
    upstream.scripts = list(scripts)
    from app.llm.live_semantic_provider import LiveSemanticProvider

    return LiveSemanticProvider(build_settings(upstream.base_url))


def _json(content: str, *, status: int = 200) -> UpstreamScript:
    return UpstreamScript(
        json_body={"choices": [{"message": {"content": content}}]}, status=status
    )


def _request() -> dict:
    return {"user_message": "你好", "protocol": {"type": "object", "properties": {}}}


def test_a_real_round_trip_returns_the_parsed_proposal(upstream):
    provider = _provider(upstream, [_json('{"reply": "你好，想吃点什么？"}')])

    assert provider.propose(_request()) == {"reply": "你好，想吃点什么？"}
    assert len(upstream.requests) == 1, "one propose is one HTTP call"
    sent = upstream.requests[0]
    assert sent["model"] == "test-model"
    assert sent["response_format"] == {"type": "json_object"}
    # The shopper's own words are the *last* user message, never buried in the
    # context blob: an earlier turn's text must not be answered instead.
    assert sent["messages"][-1] == {"role": "user", "content": "你好"}


def test_prose_instead_of_json_is_reported_not_guessed(upstream):
    provider = _provider(upstream, [_json("抱歉，我不能这样做。")])

    with pytest.raises(LLMProviderError) as exc:
        provider.propose(_request())
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_an_empty_completion_is_reported(upstream):
    provider = _provider(upstream, [_json("")])

    with pytest.raises(LLMProviderError) as exc:
        provider.propose(_request())
    assert exc.value.code == "EMPTY_MODEL_RESPONSE"


def test_an_upstream_server_error_is_retryable(upstream):
    provider = _provider(upstream, [UpstreamScript(status=503)])

    with pytest.raises(LLMProviderError) as exc:
        provider.propose(_request())
    assert exc.value.code == "TOOL_UNAVAILABLE"
    assert exc.value.retryable is True


def test_an_upstream_client_error_is_not_retryable(upstream):
    """A rejected request is not something to ask again unchanged."""
    provider = _provider(upstream, [UpstreamScript(status=400)])

    with pytest.raises(LLMProviderError) as exc:
        provider.propose(_request())
    assert exc.value.code == "TOOL_UNAVAILABLE"
    assert exc.value.retryable is False


def test_the_shopper_message_is_never_sent_as_the_only_system_text(upstream):
    """The protocol and the context travel as their own messages."""
    provider = _provider(upstream, [_json('{"reply": "好。"}')])
    provider.propose(_request())

    messages = upstream.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "protocol" in messages[0]["content"]
    assert any(
        m["role"] == "user" and "server_context" in m["content"] for m in messages
    ), messages

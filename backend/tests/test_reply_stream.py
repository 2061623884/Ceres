"""Reply streaming extractor and provider transport behaviour."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.errors import LLMProviderError
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport
from app.llm.reply_stream import ReplyStreamExtractor


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_base_url="http://localhost/v1",
        openai_api_key="test-only",
        llm_model="protocol-simulator",
    )


def _collect_reply(chunks: list[str]) -> str:
    extractor = ReplyStreamExtractor()
    out = []
    for chunk in chunks:
        piece = extractor.feed(chunk)
        if piece:
            out.append(piece)
    return "".join(out)


def test_reply_extractor_handles_chunked_plain_text():
    chunks = ['{"intent":"chat","reply":"', "你好", '世界"}']
    assert _collect_reply(chunks) == "你好世界"


def test_reply_extractor_handles_escapes_and_unicode():
    chunks = ['{"reply":"say \\"hi\\" and \u4f60', "\u597d" + '"}']
    assert _collect_reply(chunks) == 'say "hi" and 你好'


def test_streaming_propose_emits_reply_before_parse():
    deltas: list[tuple[str, bool, bool]] = []

    def stream_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("stream") is True

        def lines():
            pieces = ['{"reply":"', "你", "好", '"}']
            for piece in pieces:
                payload = {"choices": [{"delta": {"content": piece}}]}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return httpx.Response(200, content=b"".join(line.encode() for line in lines()))

    settings = _settings()
    provider = LiveSemanticProvider(
        settings,
        OpenAICompatTransport(settings, httpx.MockTransport(stream_handler)),
    )
    result = provider.propose(
        {"user_message": "你好"},
        on_reply_delta=lambda delta, final, replace: deltas.append((delta, final, replace)),
    )
    assert result["reply"] == "你好"
    assert [d[0] for d in deltas] == ["你", "好"]


def test_stream_failure_before_content_falls_back_to_post_json():
    calls = {"stream": 0, "json": 0}

    class DualTransport:
        def post_stream(self, payload, *, timeout_s=None, on_content=None):
            calls["stream"] += 1
            raise LLMProviderError("TOOL_UNAVAILABLE", "stream down", retryable=True)

        def post_json(self, payload, *, timeout_s=None):
            calls["json"] += 1
            return {"choices": [{"message": {"content": '{"reply":"fallback"}'}}]}

    deltas: list[str] = []
    provider = LiveSemanticProvider(_settings(), DualTransport())
    result = provider.propose(
        {},
        on_reply_delta=lambda delta, _final, _replace: deltas.append(delta),
    )
    assert result["reply"] == "fallback"
    assert calls == {"stream": 1, "json": 1}
    assert deltas == []


def test_stream_failure_after_content_does_not_call_post_json():
    calls = {"stream": 0, "json": 0}

    class BrokenMidStreamTransport:
        def post_stream(self, payload, *, timeout_s=None, on_content=None):
            calls["stream"] += 1
            if on_content is not None:
                on_content('{"reply":"部')
            raise LLMProviderError("TOOL_UNAVAILABLE", "mid stream", retryable=True)

        def post_json(self, payload, *, timeout_s=None):
            calls["json"] += 1
            return {"choices": [{"message": {"content": '{"reply":"second"}'}}]}

    provider = LiveSemanticProvider(_settings(), BrokenMidStreamTransport())
    with pytest.raises(LLMProviderError):
        provider.propose(
            {},
            on_reply_delta=lambda delta, _final, _replace: None,
        )
    assert calls == {"stream": 1, "json": 0}

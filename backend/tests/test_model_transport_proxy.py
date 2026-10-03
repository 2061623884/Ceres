"""Configured model endpoints are called directly, independent of shell proxies."""

import pytest

from app.llm.openai_transport import OpenAICompatTransport
from app.core.config import Settings
from support.sse_upstream import LocalUpstream, UpstreamScript, content_chunk


@pytest.mark.parametrize("streaming", [False, True])
def test_configured_model_endpoint_ignores_environment_proxy(monkeypatch, streaming):
    script = (
        UpstreamScript([content_chunk('{"reply":"ok"}'), "[DONE]"])
        if streaming else
        UpstreamScript(json_body={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})
    )
    upstream = LocalUpstream([script])
    proxy = LocalUpstream([UpstreamScript(status=502)])
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, proxy.base_url.removesuffix("/v1"))
    monkeypatch.setenv("NO_PROXY", "")
    try:
        settings = Settings(_env_file=None, OPENAI_BASE_URL=upstream.base_url,
                            OPENAI_API_KEY="test-key", LLM_MODEL="test-model")
        transport = OpenAICompatTransport(settings)
        if streaming:
            content, _ = transport.post_stream({"messages": []}, timeout_s=2)
        else:
            response = transport.post_json({"messages": []}, timeout_s=2)
            content = response["choices"][0]["message"]["content"]
        assert content == '{"reply":"ok"}'
        assert proxy.requests == []
    finally:
        upstream.close()
        proxy.close()

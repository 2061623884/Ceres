"""One-shot guard for the Ceres V3 independent-evidence failure probe."""

import re

import httpx
import httpx2
import pytest


_TARGET = re.compile(r"^/api/v1/chat/openings/[^/]+/turns/stream$")


@pytest.fixture(autouse=True)
def block_external_model_sends_for_probe(request, monkeypatch):
    if request.node.name != "test_independent_dialogue_phenomena":
        return

    def is_testserver(req):
        return req.url.host == "testserver"

    def response_for(req, client_type):
        response_type = httpx2.Response if issubclass(client_type, httpx2.Client) else httpx.Response
        return response_type(
            200,
            content=b"event: route.result\ndata: {invalid-json}\n\n",
            headers={"content-type": "text/event-stream; charset=utf-8"},
            request=req,
        )

    for client_type in (httpx.Client, httpx2.Client):
        original_send = client_type.send

        def guarded_send(self, request, *args, _original=original_send, _client_type=client_type, **kwargs):
            if is_testserver(request):
                if _TARGET.fullmatch(request.url.path):
                    return response_for(request, _client_type)
                return _original(self, request, *args, **kwargs)
            raise RuntimeError("probe blocked an external HTTPX send")

        monkeypatch.setattr(client_type, "send", guarded_send)

    for client_type in (httpx.AsyncClient, httpx2.AsyncClient):
        original_send = client_type.send

        async def guarded_async_send(self, request, *args, _original=original_send, _client_type=client_type, **kwargs):
            if is_testserver(request):
                if _TARGET.fullmatch(request.url.path):
                    return response_for(request, _client_type)
                return await _original(self, request, *args, **kwargs)
            raise RuntimeError("probe blocked an external HTTPX async send")

        monkeypatch.setattr(client_type, "send", guarded_async_send)

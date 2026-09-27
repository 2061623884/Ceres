"""A tiny local HTTP server that speaks OpenAI-compatible SSE.

Used to exercise the real ``httpx`` streaming client in ``LiveAgentProvider`` —
including fragmented tool-call arguments and delayed chunks — without any
external provider or credentials.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class UpstreamScript:
    """A scripted upstream: raw SSE frames, or one plain JSON body."""

    def __init__(
        self,
        frames: list[str | dict[str, Any]] | None = None,
        *,
        json_body: dict[str, Any] | None = None,
        delay_before_last_s: float = 0.0,
        status: int = 200,
        fail_after_frames: int | None = None,
    ):
        self.frames = frames or []
        self.json_body = json_body
        self.delay_before_last_s = delay_before_last_s
        self.status = status
        self.fail_after_frames = fail_after_frames


def _frame(payload: str | dict[str, Any]) -> bytes:
    if isinstance(payload, str):
        return f"data: {payload}\n\n".encode()
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def content_chunk(text: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


def tool_chunk(
    *,
    index: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> dict[str, Any]:
    fn: dict[str, Any] = {}
    if name is not None:
        fn["name"] = name
    if arguments is not None:
        fn["arguments"] = arguments
    entry: dict[str, Any] = {"index": index, "function": fn}
    if call_id is not None:
        entry["id"] = call_id
    return {"choices": [{"index": 0, "delta": {"tool_calls": [entry]}}]}


class LocalUpstream:
    """Serves one scripted response per request and counts the requests."""

    def __init__(self, scripts: list[UpstreamScript]):
        self.scripts = list(scripts)
        self.requests: list[dict[str, Any]] = []
        self.request_times: list[float] = []
        self.closed_early = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def next_script(self) -> UpstreamScript:
        with self._lock:
            if not self.scripts:
                return UpstreamScript([content_chunk("（无更多脚本）"), "[DONE]"])
            return self.scripts.pop(0)

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # silence test output
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode() or "{}")
                except ValueError:
                    body = {}
                with outer._lock:
                    outer.requests.append(body)
                    outer.request_times.append(time.monotonic())
                script = outer.next_script()
                if script.status != 200:
                    self.send_response(script.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if script.json_body is not None:
                    body = json.dumps(script.json_body, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                sent = 0
                try:
                    for index, payload in enumerate(script.frames):
                        if (
                            script.delay_before_last_s
                            and index == len(script.frames) - 1
                        ):
                            time.sleep(script.delay_before_last_s)
                        self.wfile.write(_frame(payload))
                        self.wfile.flush()
                        sent += 1
                        if (
                            script.fail_after_frames is not None
                            and sent >= script.fail_after_frames
                        ):
                            raise ConnectionResetError("scripted upstream failure")
                        time.sleep(0.005)
                except (BrokenPipeError, ConnectionResetError):
                    with outer._lock:
                        outer.closed_early += 1

        return Handler


def build_settings(base_url: str, **overrides: Any):
    from app.core.config import Settings

    values: dict[str, Any] = {
        "llm_mode": "live",
        "openai_base_url": base_url,
        "openai_api_key": "test-key",
        "llm_model": "test-model",
        "llm_timeout": 10.0,
    }
    values.update(overrides)
    # ``_env_file=None`` keeps the test away from any real .env file.
    return Settings(_env_file=None, **values)

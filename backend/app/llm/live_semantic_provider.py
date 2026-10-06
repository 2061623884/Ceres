"""Live provider for the low-cardinality semantic proposal protocol.

One request per propose step. The model receives a bounded, server-owned
candidate list and answers with a single JSON object. It may read authoritative
plan facts but may not author business operations, prices, stock or versions.

When an SSE consumer is attached, ``reply`` text is streamed incrementally from
the JSON body. The assembled body still passes ``extract_json_object`` before
use.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from app.core.config import Settings
from app.llm.errors import LLMProviderError
from app.llm.openai_transport import OpenAICompatTransport, project_money_for_model
from app.llm.reply_stream import ReplyStreamExtractor
from app.llm.structured_output import extract_json_object

# The outbound prompt text lives in ``app.prompts.semantic``; this module owns
# only the request shape, schema narrowing, transport and parsing.
from app.prompts.semantic import (
    CAPABILITY_COMPLETE_PROMPTS,
    CAPABILITY_EXAMPLE_MESSAGES,
    CAPABILITY_PROMPTS,
    HISTORY_COMPLETE_PROMPT,
    POLICY_COMPLETE_PROMPT,
    POLICY_SYSTEM_PROMPT,
    PROPOSAL_EXAMPLES,
    RETRIEVAL_COMPLETE_PROMPT,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

ReplyDeltaCallback = Callable[[str, bool, bool], None]


class LiveSemanticProvider:
    """JSON proposal provider with optional ``reply`` streaming."""

    def __init__(self, settings: Settings, transport: Any | None = None):
        self.settings = settings
        self._transport = transport or OpenAICompatTransport(settings)
        #: Seconds of the turn's budget left, set by the loop before each call
        #: through ``set_call_timeout``. ``None`` keeps the configured timeout.
        self._call_budget_s: float | None = None

    def supports_streaming(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return False

    def set_call_timeout(self, seconds: float) -> None:
        """Optional capability the loop uses to keep one call inside the turn."""
        self._call_budget_s = float(seconds)

    def propose(
        self,
        request: dict[str, Any],
        *,
        on_reply_delta: ReplyDeltaCallback | None = None,
        reset_stream: bool = False,
    ) -> dict[str, Any]:
        if reset_stream and on_reply_delta is not None:
            on_reply_delta("", False, True)

        payload = self._build_payload(request)
        if on_reply_delta is None:
            data = self._transport.post_json(payload, timeout_s=self._call_budget_s)
            content = self._content_from_response(data)
            return self._parse_content(content)

        extractor = ReplyStreamExtractor()
        streamed_any = False

        def on_content(chunk: str) -> None:
            nonlocal streamed_any
            streamed_any = True
            reply_piece = extractor.feed(chunk)
            if reply_piece:
                on_reply_delta(reply_piece, False, False)

        try:
            content, finish_reason = self._transport.post_stream(
                payload,
                timeout_s=self._call_budget_s,
                on_content=on_content,
            )
        except LLMProviderError:
            if streamed_any:
                raise
            data = self._transport.post_json(payload, timeout_s=self._call_budget_s)
            content = self._content_from_response(data)
            return self._parse_content(content)

        if finish_reason == "length":
            raise LLMProviderError(
                "MODEL_OUTPUT_TRUNCATED", "模型输出超过长度限制，未执行不完整提案。", retryable=True
            )
        return self._parse_content(content)

    def _build_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        context = {k: v for k, v in request.items()
                   if k not in ("user_message", "recent_messages", "protocol")}
        history = [m for m in (request.get("recent_messages") or [])[-6:]
                   if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        user_message = str(request.get("user_message") or "")
        if history and history[-1] == {"role": "user", "content": user_message}:
            history = history[:-1]
        # ``build_request`` already staged the protocol: the proposal schema while
        # understanding, the reply-only schema once retrieval ran.
        protocol = request.get("protocol") or {}
        capability = request.get("capability")
        capability_prompt = CAPABILITY_PROMPTS[capability] if capability is not None else ""
        answering = bool(request.get("query_results"))
        query_results = request.get("query_results", [])
        if any(result.get("kind") == "history" for result in query_results):
            answer_prompt = HISTORY_COMPLETE_PROMPT
        else:
            answer_prompt = (
                CAPABILITY_COMPLETE_PROMPTS[capability]
                if capability is not None
                else RETRIEVAL_COMPLETE_PROMPT
            )
        system = SYSTEM_PROMPT + ("\n" + capability_prompt if capability_prompt else "")
        if answering:
            system += answer_prompt
        if answering and all(result.get("kind") == "policy" for result in query_results):
            system = POLICY_SYSTEM_PROMPT + POLICY_COMPLETE_PROMPT
        examples = (
            [
                example
                for example in PROPOSAL_EXAMPLES
                if example[0]["user_message"] in CAPABILITY_EXAMPLE_MESSAGES[capability]
            ]
            if not answering and capability is not None
            else []
        )
        return {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system + "\nprotocol:\n" +
                    json.dumps(protocol, ensure_ascii=False)},
                *[
                    {"role": role, "content": json.dumps(content, ensure_ascii=False)}
                    for example in examples
                    for role, content in zip(("user", "assistant"), example)
                ],
                *[{"role": m["role"], "content": m["content"]} for m in history],
                {
                    "role": "user",
                    "content": json.dumps(
                        {"server_context": project_money_for_model(context)}, ensure_ascii=False
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": self.settings.llm_max_output_tokens,
            "response_format": {"type": "json_object"},
        }

    def _content_from_response(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            if choices[0].get("finish_reason") == "length":
                raise LLMProviderError(
                    "MODEL_OUTPUT_TRUNCATED", "模型输出超过长度限制，未执行不完整提案。", retryable=True
                )
        content = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise LLMProviderError("MODEL_OUTPUT_INVALID", "模型内容不是文本", retryable=True)
        content = (content or "").strip()
        if not content:
            raise LLMProviderError(
                "EMPTY_MODEL_RESPONSE",
                "模型返回了空响应",
                retryable=True,
            )
        return content

    def _parse_content(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                "MODEL_OUTPUT_INVALID", f"模型输出不是合法 JSON: {exc}", retryable=True
            ) from exc


__all__ = ["LiveSemanticProvider", "ReplyDeltaCallback", "SYSTEM_PROMPT"]

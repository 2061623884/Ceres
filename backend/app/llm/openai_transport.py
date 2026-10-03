"""Shared OpenAI-compatible chat-completions transport.

Minimal JSON transport for semantic proposals. The frozen legacy streaming
provider is unchanged; this module deliberately has no unused SSE implementation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.errors import LLMProviderError

logger = logging.getLogger(__name__)

#: Floor for a non-positive budget only. It never enlarges a positive one: a turn
#: with a hundredth of a second left gets a hundredth of a second.
MIN_CALL_TIMEOUT_S = 0.001


def project_money_for_model(value: Any) -> Any:
    """Rename and rescale every ``*_fen`` key so the model only ever sees yuan.

    A structural transform, never a search-and-replace over prose.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_fen"):
                name = key[: -len("_fen")] + "_yuan"
                out[name] = None if item is None else round(float(item) / 100.0, 2)
                continue
            out[key] = project_money_for_model(item)
        return out
    if isinstance(value, list):
        return [project_money_for_model(item) for item in value]
    return value


class OpenAICompatTransport:
    """Synchronous client for one OpenAI-compatible chat-completions endpoint."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._transport = transport

    # ------------------------------------------------------------------ request

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        return f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"

    def _client(self, timeout: httpx.Timeout) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(timeout=timeout, transport=self._transport)
        return httpx.Client(timeout=timeout, trust_env=False)

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.settings.llm_timeout, connect=10.0)

    def _timeout_for_call(self, budget_s: float | None) -> httpx.Timeout:
        """The timeout of one call, never longer than the remaining turn budget.

        A caller that knows how much of its own budget is left hands it over here,
        so a single request cannot outlive the turn by a whole ``llm_timeout``.
        Without a budget the configured timeout applies unchanged, and it is never
        raised: the budget can only make this call stricter. That includes a very
        small positive budget — it bounds both the read and the connect phase
        exactly, instead of being rounded up into a longer call than the turn has.
        """
        if budget_s is None:
            return self._timeout()
        budget = float(budget_s)
        if budget <= 0:
            # No time left at all. The loop refuses before asking; this keeps a
            # degenerate budget from ever becoming "no timeout".
            budget = MIN_CALL_TIMEOUT_S
        return httpx.Timeout(
            min(float(self.settings.llm_timeout), budget), connect=min(10.0, budget)
        )

    def post_json(
        self, payload: dict[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        try:
            with self._client(self._timeout_for_call(timeout_s)) as client:
                resp = client.post(self._url(), headers=self._headers(), json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            logger.error("LLM API timeout: %s", exc)
            raise LLMProviderError("MODEL_TIMEOUT", "Model request timed out", retryable=True)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "LLM API HTTP error: %s - %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise LLMProviderError(
                "TOOL_UNAVAILABLE",
                f"Model API error: {exc.response.status_code}",
                retryable=exc.response.status_code >= 500,
            )
        except httpx.HTTPError as exc:
            logger.error("LLM API network error: %s", exc)
            raise LLMProviderError("TOOL_UNAVAILABLE", f"Model network error: {exc}", retryable=True)

    def post_stream(
        self,
        payload: dict[str, Any],
        *,
        timeout_s: float | None = None,
        on_content: Callable[[str], None] | None = None,
    ) -> tuple[str, str | None]:
        """Stream chat completion chunks; return assembled text and finish_reason."""
        stream_payload = {**payload, "stream": True}
        finish_reason: str | None = None
        parts: list[str] = []
        try:
            with self._client(self._timeout_for_call(timeout_s)) as client:
                with client.stream(
                    "POST",
                    self._url(),
                    headers=self._headers(),
                    json=stream_payload,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data = line[5:].strip()
                        else:
                            data = line.strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        for choice in event.get("choices") or []:
                            if not isinstance(choice, dict):
                                continue
                            reason = choice.get("finish_reason")
                            if isinstance(reason, str):
                                finish_reason = reason
                            delta = choice.get("delta")
                            if not isinstance(delta, dict):
                                continue
                            content = delta.get("content")
                            if not isinstance(content, str) or not content:
                                continue
                            parts.append(content)
                            if on_content is not None:
                                on_content(content)
        except httpx.TimeoutException as exc:
            logger.error("LLM API stream timeout: %s", exc)
            raise LLMProviderError("MODEL_TIMEOUT", "Model request timed out", retryable=True)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "LLM API HTTP error: %s - %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise LLMProviderError(
                "TOOL_UNAVAILABLE",
                f"Model API error: {exc.response.status_code}",
                retryable=exc.response.status_code >= 500,
            )
        except httpx.HTTPError as exc:
            logger.error("LLM API network error: %s", exc)
            raise LLMProviderError("TOOL_UNAVAILABLE", f"Model network error: {exc}", retryable=True)
        return "".join(parts), finish_reason


__all__ = ["OpenAICompatTransport", "project_money_for_model"]

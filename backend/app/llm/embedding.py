"""Embedding adapter — a small, independent provider for the vector route.

Embedding is *not* chat: it has its own model, its own dimension and its own
instruction convention, so it gets its own configuration rather than being
folded into ``OPENAI_BASE_URL`` / ``LLM_MODEL``. Nothing here assumes a chat
endpoint can embed.

Two rules the rest of the system relies on:

* The **query instruction is applied to queries only**. Documents are embedded
  exactly as the model card says — which, for a model that declares none, means
  no prefix at all. Adding an instruction to both sides silently changes what
  the vectors mean.
* Every vector is checked against the declared contract (dimension, finiteness,
  unit norm) before it is stored or scored. A malformed vector is an error, not
  a bad match.

Credentials are read from the **process environment** by the offline CLI. This
module never loads a dotenv file on its own, and never logs a key.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

logger = logging.getLogger(__name__)

DEFAULT_DIMENSION = 1024

ENV_BASE_URL = "EMBEDDING_BASE_URL"
ENV_API_KEY = "EMBEDDING_API_KEY"
ENV_MODEL = "EMBEDDING_MODEL"
ENV_REVISION = "EMBEDDING_REVISION"
ENV_DIMENSION = "EMBEDDING_DIMENSION"
ENV_QUERY_INSTRUCTION = "EMBEDDING_QUERY_INSTRUCTION"
ENV_DOCUMENT_INSTRUCTION = "EMBEDDING_DOCUMENT_INSTRUCTION"
ENV_TIMEOUT = "EMBEDDING_TIMEOUT"


class EmbeddingUnavailable(RuntimeError):
    """The vector route cannot run. Reported as a degradation, never hidden."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EmbeddingContractError(ValueError):
    """A vector violated the declared contract. Never silently accepted."""


@dataclass(frozen=True)
class EmbeddingContract:
    """Exactly what the stored vectors mean.

    Any change here makes existing vectors incomparable and forces an offline
    rebuild; that is why the contract key is part of every cache lookup and of
    the index manifest.
    """

    model: str
    revision: str
    dimension: int
    normalize: bool = True
    dtype: str = "float32"
    query_instruction: str = ""
    document_instruction: str | None = None

    def as_dict(self) -> dict[str, Any]:
        from app.services.retrieval_projection import TEXT_TEMPLATE_VERSION
        return {
            "text_template_version": TEXT_TEMPLATE_VERSION,
            "model": self.model,
            "revision": self.revision,
            "dimension": int(self.dimension),
            "dtype": self.dtype,
            "normalize": bool(self.normalize),
            "query_instruction": self.query_instruction,
            "document_instruction": self.document_instruction,
        }


class EmbeddingProvider(Protocol):
    """The seam tests inject a deterministic provider through."""

    contract: EmbeddingContract

    def embed(self, texts: Sequence[str], *, kind: str) -> list[list[float]]: ...


def apply_instruction(text: str, contract: EmbeddingContract, *, kind: str) -> str:
    """Prefix a query with the query instruction, and only a query."""
    if kind == "query" and contract.query_instruction:
        return f"{contract.query_instruction}{text}"
    if kind == "document" and contract.document_instruction:
        return f"{contract.document_instruction}{text}"
    return text


class HttpEmbeddingProvider:
    """OpenAI-compatible ``/embeddings`` endpoint.

    Deliberately independent of the chat transport: the chat client hard-codes
    ``/chat/completions`` and its payload shape, and an embedding request is
    neither.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        contract: EmbeddingContract,
        timeout: float = 30.0,
        transport: Any | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self.contract = contract
        self.timeout = float(timeout)
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Any) -> "HttpEmbeddingProvider":
        """Use the application's resolved configuration (dotenv + env overrides).

        The offline CLI still reads only process env unless --env-file is explicit.
        Do not implicitly reuse chat credentials or a chat model for embedding.
        """
        return cls.from_env({
            key: str(getattr(settings, key.lower(), "") or "")
            for key in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL, ENV_REVISION,
                        ENV_DIMENSION, ENV_QUERY_INSTRUCTION,
                        ENV_DOCUMENT_INSTRUCTION, ENV_TIMEOUT)
        })

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "HttpEmbeddingProvider":
        """Build from the process environment. No dotenv loading, no logging of secrets."""
        env = environ if environ is not None else os.environ
        base_url = (env.get(ENV_BASE_URL) or "").strip()
        api_key = (env.get(ENV_API_KEY) or "").strip()
        model = (env.get(ENV_MODEL) or "").strip()
        if not base_url or not model:
            raise EmbeddingUnavailable(
                "EMBEDDING_NOT_CONFIGURED",
                f"set {ENV_BASE_URL} and {ENV_MODEL} in the process environment to build vectors",
            )
        dimension_raw = (env.get(ENV_DIMENSION) or "").strip()
        try:
            dimension = int(dimension_raw) if dimension_raw else DEFAULT_DIMENSION
        except ValueError:
            raise EmbeddingUnavailable(
                "EMBEDDING_NOT_CONFIGURED", f"{ENV_DIMENSION} must be an integer"
            ) from None
        contract = EmbeddingContract(
            model=model,
            revision=(env.get(ENV_REVISION) or "").strip(),
            dimension=dimension,
            query_instruction=(env.get(ENV_QUERY_INSTRUCTION) or ""),
            document_instruction=(env.get(ENV_DOCUMENT_INSTRUCTION) or None),
        )
        timeout_raw = (env.get(ENV_TIMEOUT) or "").strip()
        timeout = float(timeout_raw) if timeout_raw else 30.0
        return cls(base_url=base_url, api_key=api_key, contract=contract, timeout=timeout)

    def embed(self, texts: Sequence[str], *, kind: str) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.contract.model,
            "input": [apply_instruction(text, self.contract, kind=kind) for text in texts],
        }
        import httpx

        url = f"{self.base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout, connect=10.0)}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            with httpx.Client(**client_kwargs) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailable("EMBEDDING_TIMEOUT", f"embedding request timed out: {exc}") from None
        except httpx.HTTPStatusError as exc:
            # The status and the endpoint are useful; the key and body are not logged.
            raise EmbeddingUnavailable(
                "EMBEDDING_HTTP_ERROR",
                f"embedding endpoint returned HTTP {exc.response.status_code}",
            ) from None
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingUnavailable("EMBEDDING_TRANSPORT_ERROR", f"embedding transport failed: {exc}") from None
        return self._parse(body, expected=len(texts))

    def _parse(self, body: Any, *, expected: int) -> list[list[float]]:
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingUnavailable(
                "EMBEDDING_MALFORMED_RESPONSE",
                f"expected {expected} embeddings, got {len(data) if isinstance(data, list) else 'none'}",
            )
        # The contract of the endpoint is that ``index`` gives the position in
        # the request. Responses are not guaranteed to arrive in order, so the
        # index is honoured — silently zipping them would attach another text's
        # vector to this document.
        positions = [entry.get("index") if isinstance(entry, dict) else None for entry in data]
        if (any(type(position) is not int for position in positions)
                or sorted(positions) != list(range(expected))):
            raise EmbeddingUnavailable("EMBEDDING_MALFORMED_RESPONSE", "invalid or duplicate embedding index")
        ordered = sorted(range(len(data)), key=lambda position: positions[position])
        vectors: list[list[float]] = []
        for position in ordered:
            entry = data[position]
            raw = entry.get("embedding") if isinstance(entry, dict) else None
            if not isinstance(raw, list):
                raise EmbeddingUnavailable("EMBEDDING_MALFORMED_RESPONSE", "embedding entry has no vector")
            try:
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in raw):
                    raise ValueError("invalid number")
                vectors.append([float(v) for v in raw])
            except (TypeError, ValueError, OverflowError):
                raise EmbeddingUnavailable("EMBEDDING_MALFORMED_RESPONSE", "embedding has invalid numbers") from None
        return vectors


def validate_and_normalize(vectors: list[list[float]], contract: EmbeddingContract) -> list[list[float]]:
    """Enforce the contract on freshly produced vectors, then normalize.

    Dimension and finiteness are checked *before* normalization, so a provider
    that quietly switched model size is caught instead of being rescaled into
    something that looks plausible.
    """
    from app.services.retrieval_index import normalize_vector, validate_vector

    out: list[list[float]] = []
    if contract.dimension <= 0 or contract.dtype != "float32" or not contract.normalize:
        raise EmbeddingContractError("V1 requires positive dimension, float32 and normalized vectors")
    for vector in vectors:
        if not contract.normalize:
            # Still finite, still the declared width; just not rescaled.
            if len(vector) != contract.dimension:
                raise EmbeddingContractError(
                    f"vector dimension {len(vector)} != contract dimension {contract.dimension}"
                )
            out.append([float(v) for v in vector])
            continue
        try:
            out.append(normalize_vector(vector))
            validate_vector(out[-1], dimension=contract.dimension)
        except ValueError as exc:
            raise EmbeddingContractError(str(exc)) from None
    return out


__all__ = [
    "EmbeddingContract",
    "EmbeddingContractError",
    "EmbeddingProvider",
    "EmbeddingUnavailable",
    "HttpEmbeddingProvider",
    "apply_instruction",
    "validate_and_normalize",
]

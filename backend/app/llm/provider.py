"""LLM provider factory — live only for product runtime.

There is exactly one provider in the product: the semantic proposal provider.
The tool-call agent provider and the legacy requirement parser provider were
selectable alternatives of a retired decision chain; keeping a factory for them
would be a way back into it, so there is none.
"""

from __future__ import annotations

from app.core.config import get_settings


def get_semantic_provider():
    """The provider for the low-cardinality proposal protocol.

    Same live-only requirement as everything else: the semantic loop never
    degrades into a text-matching route when credentials are missing.
    """
    settings = get_settings()
    if settings.llm_mode != "live" or not settings.is_live_llm_configured():
        raise RuntimeError(
            "Live semantic provider is required. Set LLM_MODE=live and configure "
            "OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL. Mock is disabled."
        )
    from app.llm.live_semantic_provider import LiveSemanticProvider

    return LiveSemanticProvider(settings)

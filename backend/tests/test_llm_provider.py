"""LLM provider smoke — live only (runtime mock removed).

Named ``test_smoke_live`` on purpose: it is the one test the offline regression
command deselects, because it is the only one that would talk to a real model.
The runtime's only provider is the semantic one, so that is what it exercises.
"""

import pytest


def test_smoke_live():
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.is_live_llm_configured():
        pytest.skip("Live LLM not configured")
    from app.llm.live_semantic_provider import LiveSemanticProvider

    provider = LiveSemanticProvider(settings)
    proposal = provider.propose(
        {"user_message": "你好", "protocol": {"type": "object", "properties": {}}}
    )
    assert isinstance(proposal, dict)

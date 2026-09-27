"""Deployment regressions; HTTP doubles test contracts, not semantic quality."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.llm.embedding import EmbeddingContract, HttpEmbeddingProvider
from app.prompts.semantic import PROPOSAL_EXAMPLES
from app.services.retrieval_service import RetrievalService

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_runtime_embedding_reads_same_settings_as_chat(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('EMBEDDING_BASE_URL=https://embed.example/v1\n'
                   'EMBEDDING_API_KEY=test-only\nEMBEDDING_MODEL=real-embedding\n'
                   'EMBEDDING_DIMENSION=2\nEMBEDDING_QUERY_INSTRUCTION=query: \n', encoding='utf-8')
    for key in ('BASE_URL', 'API_KEY', 'MODEL', 'DIMENSION', 'QUERY_INSTRUCTION'):
        monkeypatch.delenv('EMBEDDING_' + key, raising=False)
    settings = Settings(_env_file=env)
    monkeypatch.setattr('app.core.config.get_settings', lambda: settings)
    service = RetrievalService(None, store_id='s', delivery_zone_id='z')
    provider = service._provider()
    assert provider is not None
    assert provider.contract.model == 'real-embedding'
    assert provider.contract.dimension == 2
    assert provider.base_url == 'https://embed.example/v1'


def test_document_instruction_is_applied_exactly_once_by_http_provider():
    from scripts.build_retrieval_index import _embed_documents
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'data': [{'index': 0, 'embedding': [1., 0.]}]})

    provider = HttpEmbeddingProvider(
        base_url='https://embed.example/v1', api_key='test-only',
        contract=EmbeddingContract(model='test', revision='', dimension=2,
                                   document_instruction='document: '),
        transport=httpx.MockTransport(handler),
    )
    _embed_documents([SimpleNamespace(doc_id='dish:1', text='鸡翅')], provider, reuse={})
    assert payloads[0]['input'] == ['document: 鸡翅']


def test_build_requires_explicit_lexical_mode_when_credentials_are_missing(monkeypatch):
    from scripts.build_retrieval_index import _embedding_provider
    monkeypatch.delenv('EMBEDDING_BASE_URL', raising=False)
    monkeypatch.delenv('EMBEDDING_MODEL', raising=False)
    with pytest.raises(SystemExit, match='--no-embed'):
        _embedding_provider(SimpleNamespace(no_embed=False, env_file=None))
    assert _embedding_provider(SimpleNamespace(no_embed=True, env_file=None)) is None


def _example_pair(message: str):
    """The retrieving round and the post-retrieval round of one example topic."""
    initial = next(
        answer
        for request, answer in PROPOSAL_EXAMPLES
        if request.get('user_message') == message and not request.get('query_results')
    )
    final = next(
        answer
        for request, answer in PROPOSAL_EXAMPLES
        if request.get('user_message') == message and request.get('query_results')
    )
    return initial, final


def test_purchase_examples_declare_intent_before_not_after_retrieval():
    """Purchase intent belongs to the retrieving round, never to the round after.

    The post-retrieval round then either carries the mutation (a product the
    shopper named) or asks the one slot that is still missing (self-cook vs
    ready-made); either way the flag is not restated.
    """
    dish_initial, dish_final = _example_pair('我想吃番茄炒蛋')
    assert dish_initial.get('purchase_requested') is True
    # Never restated after the retrieval round.
    assert 'purchase_requested' not in dish_final
    # The dish example's post-retrieval round is the fulfillment-mode question,
    # so it deliberately holds no mutation.
    assert not dish_final.get('mutations')
    assert dish_final['understanding']['new_goal']['fulfillment_mode'] == 'unspecified'
    assert '自己做' in dish_final['reply'] and '现成' in dish_final['reply']

    milk_initial, milk_final = _example_pair('买一盒牛奶')
    # The product example declares the same intent through typed understanding
    # (not the legacy flag), and its post-retrieval round carries the mutation.
    assert milk_initial.get('understanding', {}).get('speech_act') == 'request_action'
    assert 'purchase_requested' not in milk_initial
    assert milk_final.get('mutations')
    assert 'purchase_requested' not in milk_final

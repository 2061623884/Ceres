"""Deployment regressions; HTTP doubles test contracts, not semantic quality."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.agent.protocol import parse_proposal
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


def _example_for(message: str):
    """The one-pass example for this user message (spec rule 10: one call, not two)."""
    return next(
        answer
        for request, answer in PROPOSAL_EXAMPLES
        if request.get('user_message') == message
    )


def test_purchase_examples_declare_intent_and_lookup_in_the_same_pass():
    """Purchase intent and the lookup it needs are one proposal, not two rounds.

    There is no longer a retrieving round followed by a separate round that
    restates the intent (spec rule 1): the target and its lookups are the same
    model call.
    """
    dish = _example_for('我想吃番茄炒蛋')
    assert dish['target']['intent'] == 'buy'
    assert dish['target']['name'] == '番茄炒蛋'
    assert any(lookup['kind'] == 'dish' for lookup in dish['lookups'])

    milk = _example_for('买一盒牛奶')
    assert milk['target']['intent'] == 'buy'
    assert milk['target']['name'] == '牛奶'
    assert any(lookup['kind'] == 'product' for lookup in milk['lookups'])

    simple_dinner = parse_proposal(_example_for('今晚想做顿简单的饭'))
    assert simple_dinner.understanding.new_goal.fulfillment_mode == 'self_cook'

    self_cook = parse_proposal(
        _example_for('今晚自己做一道菜，预算30元，不吃鸡蛋，你帮我推荐一道')
    )
    assert self_cook.understanding.new_goal.fulfillment_mode == 'self_cook'
    assert self_cook.understanding.new_goal.constraints.budget_yuan == 30
    assert self_cook.understanding.new_goal.constraints.excluded_ingredients == ['鸡蛋']

    eat_dish = parse_proposal(_example_for('我想吃番茄炒蛋'))
    assert eat_dish.understanding.new_goal.fulfillment_mode == 'unspecified'

    named_dish = _example_for('今晚自己做酸汤肥牛，预算100元，不吃鸡蛋')
    parsed = parse_proposal(named_dish)
    assert parsed.understanding.new_goal.target_name == '酸汤肥牛'
    assert parsed.understanding.new_goal.fulfillment_mode == 'self_cook'
    assert parsed.understanding.new_goal.constraints.budget_yuan == 100
    assert parsed.understanding.new_goal.constraints.excluded_ingredients == ['鸡蛋']
    assert [(lookup.kind, lookup.query) for lookup in parsed.lookups] == [
        ('dish', '酸汤肥牛'),
    ]
    assert not parsed.queries


def test_supply_gap_opt_in_example_reuses_pending_real_dish_and_question():
    request, proposal = next(
        (request, proposal)
        for request, proposal in PROPOSAL_EXAMPLES
        if request.get('user_message') == '那就先买能买到的'
    )
    parsed = parse_proposal(proposal)

    assert request['pending_clarifications'][0]['slot'] == 'supply_gap_choice'
    assert request['goal_candidate']['target_name'] == '酸汤肥牛'
    assert parsed.understanding.new_goal.target_name == '酸汤肥牛'
    assert parsed.understanding.intent == 'buy'
    assert [(lookup.kind, lookup.query) for lookup in parsed.lookups] == [
        ('dish', '酸汤肥牛'),
    ]
    assert parsed.resolved_questions == ['q-gap-example']


def test_answer_stage_gets_no_capability_examples_and_answer_schema(monkeypatch):
    """Once retrieval ran, the live payload drops the capability examples."""
    from app.core.config import Settings
    from app.llm.live_semantic_provider import LiveSemanticProvider
    from app.agent.protocol import answer_schema, proposal_schema

    settings = Settings(_env_file=None)
    provider = LiveSemanticProvider(settings)

    understanding_payload = provider._build_payload(
        {
            "user_message": "我想吃番茄炒蛋",
            "capability": "purchase_modify",
            "protocol": proposal_schema(),
        }
    )
    answer_payload = provider._build_payload(
        {
            "user_message": "我想吃番茄炒蛋",
            "capability": "purchase_modify",
            "query_results": [{"kind": "lookup", "status": "completed"}],
            "protocol": answer_schema(),
        }
    )

    system_messages = [m for m in understanding_payload['messages'] if m['role'] == 'system']
    assert len(understanding_payload['messages']) > len(system_messages)
    example_pairs = (len(understanding_payload['messages']) - len(system_messages)
                      - 2)  # server_context + user_message, no history
    assert example_pairs > 0

    answer_system_messages = [m for m in answer_payload['messages'] if m['role'] == 'system']
    # No example turns at all once retrieval has run.
    assert len(answer_payload['messages']) - len(answer_system_messages) == 2

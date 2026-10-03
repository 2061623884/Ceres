"""Phase 1 product binding and dish switching through the real SSE workflow."""

from pathlib import Path

import pytest

from app.agent.graph.nodes.mutation import _resolve_named_target
from app.agent.protocol import CandidateSet
from app.agent.tools.read import ReadTools
from app.schemas.goal import Goal, GoalCandidate, TurnDecision
from support import create_session, post_turn
from support.semantic_agent import request_new


@pytest.fixture()
def indexed_client(client, test_db_url, monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.services.retrieval_index import publish, write_index
    from app.services.retrieval_projection import build_projection

    database = Path(test_db_url.removeprefix("sqlite:///"))
    projection, dictionary = build_projection(database)
    index_root = tmp_path / "index"
    write_index(
        target_dir=index_root / "phase1",
        projection=projection,
        dictionary=dictionary,
        embedding=None,
        vectors=None,
    )
    publish(index_root, "phase1")
    monkeypatch.setenv("RETRIEVAL_INDEX_DIR", str(index_root))
    monkeypatch.setenv("RETRIEVAL_MODE", "lexical")
    get_settings.cache_clear()
    return client


@pytest.mark.parametrize("name", ["可乐", "牛奶"])
def test_common_product_name_builds_the_top_real_lookup_hit(
    indexed_client, semantic_provider, monkeypatch, name
):
    lookup_hits = []
    original = ReadTools.serve

    def record(self, proposal, candidates, *, lookup_limit):
        results = original(self, proposal, candidates, lookup_limit=lookup_limit)
        lookup_hits.extend(
            candidates.resolve(match["ref"]).target_id
            for match in results[0]["matches"]
        )
        return results

    monkeypatch.setattr(ReadTools, "serve", record)
    provider = semantic_provider([
        {**request_new("product", name), "lookups": [{"kind": "product", "query": name}]}
    ])
    sid = create_session(indexed_client)
    response = post_turn(indexed_client, sid, "买" + name)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["route"] == "prepare", body
    assert body["plan"]["items"][0]["sku_id"] == lookup_hits[0]
    assert not body["pending_clarifications"]
    assert len(provider.requests) == 1
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_product_binding_uses_current_lookup_order_instead_of_candidate_order():
    candidates = CandidateSet()
    previous = candidates.allocate("product", "previous", "上一轮商品")
    second = candidates.allocate("product", "second", "可乐 500毫升")
    first = candidates.allocate("product", "first", "可乐 330毫升")
    goal = Goal(kind="product_purchase", target_name="可乐")
    decision = TurnDecision(
        route="mutation", mutation_action="prepare", readiness="ready",
        write_blocked=False, reason_code="READY", goal=goal,
        candidate=GoalCandidate(ref="goal", goal=goal, relation="new", target_name="可乐"),
    )
    results = [{"lookup_kind": "product", "matches": [
        {"ref": first.ref, "match_kind": "lexical"},
        {"ref": second.ref, "match_kind": "lexical"},
    ]}]
    assert _resolve_named_target(decision, results, candidates) == first
    assert first != previous


def test_switch_to_a_new_dish_replaces_the_displayed_list_and_keeps_cart(
    indexed_client, semantic_provider
):
    semantic_provider([
        {**request_new("dish", "番茄炒蛋"), "lookups": [{"kind": "dish", "query": "番茄炒蛋"}]},
        {**request_new("dish", "宫保鸡丁", relation="switch"),
         "lookups": [{"kind": "dish", "query": "宫保鸡丁"}]},
    ])
    sid = create_session(indexed_client)
    first_response = post_turn(indexed_client, sid, "我要番茄炒蛋")
    assert first_response.status_code == 200, first_response.json()
    first = first_response.json()
    assert first["plan"]["targets"][0]["target_id"] == "dish-fanqie-chao-dan"
    assert "按食材准备" in first["message"]
    assert "想买现成的可以告诉我" in first["message"]
    cart_before = indexed_client.get("/api/v1/cart").json()["items"]
    second_response = post_turn(indexed_client, sid, "换成宫保鸡丁", first)
    assert second_response.status_code == 200, second_response.json()
    second = second_response.json()
    assert second["route"] == "prepare", second
    assert "按食材准备" in second["message"]
    assert "想买现成的可以告诉我" in second["message"]
    assert second["task_id"] != first["task_id"]
    assert second["plan"]["plan_id"] != first["plan"]["plan_id"]
    assert [target["name"] for target in second["plan"]["targets"]] == ["宫保鸡丁"]
    assert "番茄" not in " ".join(item["name"] for item in second["plan"]["items"])
    current = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert current["plan"]["plan_id"] == second["plan"]["plan_id"]
    assert indexed_client.get("/api/v1/cart").json()["items"] == cart_before


@pytest.mark.parametrize("match_kind", ["fuzzy", "lexical", "semantic", "fused"])
def test_similar_dish_hit_is_not_bound_as_the_named_dish(match_kind):
    candidates = CandidateSet()
    dish = candidates.allocate("dish", "dish-fanqie-chao-dan", "番茄炒蛋")
    goal = Goal(kind="meal_plan", target_name="蕃茄炒蛋")
    decision = TurnDecision(
        route="mutation", mutation_action="prepare", readiness="ready",
        write_blocked=False, reason_code="READY", goal=goal,
        candidate=GoalCandidate(ref="goal", goal=goal, relation="new", target_name="蕃茄炒蛋"),
    )
    results = [{"lookup_kind": "dish", "matches": [
        {"ref": dish.ref, "match_kind": match_kind},
    ]}]
    assert _resolve_named_target(decision, results, candidates) is None

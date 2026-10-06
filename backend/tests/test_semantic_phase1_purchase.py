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


def test_named_dish_purchase_derives_lookup_when_proposal_omits_lookups(
    indexed_client, semantic_provider, monkeypatch
):
    served_lookups = []
    original = ReadTools.serve

    def record(self, proposal, candidates, *, lookup_limit):
        served_lookups.extend((lookup.kind, lookup.query) for lookup in proposal.lookups)
        return original(self, proposal, candidates, lookup_limit=lookup_limit)

    monkeypatch.setattr(ReadTools, "serve", record)
    provider = semantic_provider([
        request_new(
            "dish",
            "酸汤肥牛",
            mode="self_cook",
            constraints={"budget_yuan": 100},
        )
    ])
    sid = create_session(indexed_client)

    response = post_turn(indexed_client, sid, "今晚自己做酸汤肥牛，预算100元")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert served_lookups == [("dish", "酸汤肥牛")], {
        key: body.get(key)
        for key in ("status", "error", "message", "route", "action_results")
    }
    assert body["pending_clarifications"][0]["slot"] == "supply_gap_choice", body
    assert "金针菇" in body["pending_clarifications"][0]["question"], body
    assert body["plan"] is None and body["task_id"] is None, body
    assert provider.remaining() == 0
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


def test_named_product_does_not_build_a_semantic_neighbor_as_a_substitute(
    client, semantic_provider, monkeypatch
):
    def serve_semantic_neighbor(self, proposal, candidates, *, lookup_limit):
        neighbor = candidates.allocate(
            "product", "demo:cream-cheese-200g", "奶油奶酪 200克"
        )
        return [{
            "kind": "lookup",
            "lookup_kind": "product",
            "query": "冰淇淋",
            "status": "completed",
            "retrieval_status": "ok",
            "matches": [{
                "ref": neighbor.ref,
                "name": neighbor.name,
                "target_id": neighbor.target_id,
                "match_kind": "semantic",
            }],
        }]

    monkeypatch.setattr(ReadTools, "serve", serve_semantic_neighbor)
    provider = semantic_provider([{
        **request_new("product", "冰淇淋"),
        "lookups": [{"kind": "product", "query": "冰淇淋"}],
    }])
    sid = create_session(client)
    empty_cart = client.get("/api/v1/cart").json()
    add_to_cart = client.post("/api/v1/cart/items", json={
        "sku_id": "demo:eggs-fresh-6pack",
        "quantity": 1,
        "expected_cart_version": empty_cart["version"],
    })
    assert add_to_cart.status_code == 200, add_to_cart.text
    cart_before = add_to_cart.json()

    response = post_turn(client, sid, "买一盒冰淇淋")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["plan"] is None, body
    assert body["plan_effect"] == "keep", body
    assert "没有找到" in body["message"], body
    assert "奶油奶酪" not in body["message"], body
    assert not body["pending_clarifications"], body
    assert all(action["status"] != "failed" for action in body["action_results"]), body
    assert client.get("/api/v1/cart").json() == cart_before


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

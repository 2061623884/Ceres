"""Cola facts and selection use the existing Guide and confirmation APIs."""

import uuid

import pytest

from support import create_session, post_turn, send_turn
from support.semantic_agent import Continuation, pick
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_cola_comparison_returns_five_verified_cards_without_purchase(
    indexed_client, semantic_provider, run,
):
    def answer(request):
        result = request["query_results"][0]
        assert result["kind"] == "compare"
        rows = result["sellable_products"]
        assert len(rows) == 5, rows
        return {"reply": "按整包价格和每升价格比较，选择后再生成清单。",
                "display_refs": [row["ref"] for row in rows]}

    semantic_provider([{"reads": [{"kind": "compare", "topic": "可乐"}]}, Continuation(answer)])
    sid = create_session(indexed_client, page="category", category_id="beverage")
    result = post_turn(indexed_client, sid, "比较一下可乐，先看看有哪些")
    assert result.status_code == 200, result.text
    body = result.json()
    cards = body["product_cards"]
    assert len(cards) == 5
    assert all(card["sku_id"] != "demo:cola-330ml" for card in cards)
    six = next(card for card in cards if card["pack_count"] == 6)
    assert (six["item_volume_ml"], six["total_volume_ml"], six["price_fen"]) == (330, 1980, 1800)
    assert six["price_per_litre_yuan"] == 9.09
    assert all(card["brand"] in ("可口可乐", "百事可乐") for card in cards)
    assert body["plan"] is None and body["plan_effect"] == "keep"
    restored = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["product_cards"] == cards
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def display_comparison(request):
    rows = request["query_results"][0]["sellable_products"]
    return {"reply": "以下是符合条件的可乐。" if rows else "没有符合这些条件的可乐，不会改动原清单。",
            "display_refs": [row["ref"] for row in rows]}


@pytest.mark.parametrize("run", [1, 2])
def test_empty_comparison_rejects_reused_prior_card_refs(indexed_client, semantic_provider, run):
    def stale_answer(request):
        assert request["query_results"][0]["sellable_products"] == []
        return {"reply": "没有符合条件的可乐。",
                "display_refs": [row["ref"] for row in request["displayed_candidates"]]}

    semantic_provider([
        {"reads": [{"kind": "compare", "topic": "可乐"}]}, Continuation(display_comparison),
        {"reads": [{"kind": "compare", "topic": "可乐"}],
         "constraints": {"specification": {"brand": "没有这个品牌"}}}, Continuation(stale_answer),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "比较可乐")
    empty = send_turn(indexed_client, sid, "只看没有这个品牌", first)
    assert empty["product_cards"] == []
    assert indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["product_cards"] == []
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_empty_comparison_clears_prior_candidates_on_session_restore(indexed_client, semantic_provider, run):
    semantic_provider([
        {"reads": [{"kind": "compare", "topic": "可乐"}]}, Continuation(display_comparison),
        {"reads": [{"kind": "compare", "topic": "可乐"}],
         "constraints": {"specification": {"brand": "没有这个品牌"}}}, Continuation(display_comparison),
    ])
    sid = create_session(indexed_client)
    first = send_turn(indexed_client, sid, "比较可乐")
    assert len(first["product_cards"]) == 5
    empty = send_turn(indexed_client, sid, "只看没有这个品牌的可乐", first)
    assert empty["product_cards"] == []
    restored = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["product_cards"] == []
    assert restored["plan"] is None
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_cola_filters_change_and_clear_in_existing_session(indexed_client, semantic_provider, run):
    conditions = [({"brand": "百事可乐"}, 1), ({"brand": "any"}, 5),
                  ({"item_volume_ml": 500}, 2), ({"item_volume_ml": 0}, 5),
                  ({"packaging": "bottle"}, 2), ({"packaging": "any"}, 5),
                  ({"pack_mode": "multi"}, 1), ({"pack_mode": "any"}, 5),
                  ({"pack_count": 6}, 1), ({"pack_count": 0}, 5),
                  ({"max_price_yuan": 3}, 1), ({"max_price_yuan": 0}, 5)]
    proposals = []
    for condition, _ in conditions:
        proposals.extend([{"reads": [{"kind": "compare", "topic": "可乐"}],
                           "constraints": {"specification": condition}}, Continuation(display_comparison)])
    semantic_provider(proposals)
    sid = create_session(indexed_client)
    previous = None
    for condition, count in conditions:
        previous = send_turn(indexed_client, sid, f"按{condition}重新比较可乐", previous)
        assert len(previous["product_cards"]) == count, previous
        assert previous["plan"] is None
        assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_comparison_choice_revision_ack_and_explicit_confirmation(indexed_client, semantic_provider, run):
    def choose(request):
        displayed = request["displayed_candidates"][0]
        assert displayed["target_id"] == "demo:cn-coke-original-330ml-6can"
        row = next(p for p in request["candidates"]["products"] if p["ref"] == displayed["ref"])
        return pick("product", row)

    semantic_provider([
        {"reads": [{"kind": "compare", "topic": "可乐"}],
         "constraints": {"specification": {"brand": "可口可乐", "pack_mode": "multi", "max_price_yuan": 20}}},
        Continuation(display_comparison), choose,
        {"reply": "清单先保留，等您明确确认后再加购。"},
        {"reads": [{"kind": "compare", "topic": "可乐"}],
         "constraints": {"specification": {"max_price_yuan": 1}}}, Continuation(display_comparison),
    ])
    sid = create_session(indexed_client)
    shown = send_turn(indexed_client, sid, "比较可口可乐多件装，整包不超过20元")
    assert len(shown["product_cards"]) == 1 and shown["plan"] is None
    prepared = send_turn(indexed_client, sid, "选这款生成清单", shown)
    assert prepared["plan"]["items"][0]["sku_id"] == "demo:cn-coke-original-330ml-6can"
    assert prepared["plan"]["selected_total_fen"] == 1800
    ack = send_turn(indexed_client, sid, "好的", prepared)
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    before = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    empty = send_turn(indexed_client, sid, "只看1元以下的可乐", ack)
    assert empty["product_cards"] == [] and empty["plan_effect"] == "keep"
    after = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert after["plan"] == before["plan"]
    # Read filters do not retroactively revoke or authorize an existing purchase.
    plan = after["plan"]
    revision = indexed_client.post(
        f"/api/v1/guide/tasks/{prepared['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()), "expected_session_version": after["session_version"],
              "expected_state_version": after["state_version"], "base_plan_id": plan["plan_id"],
              "base_plan_version": plan["plan_version"], "coverage_intent": "full",
              "items": [{"sku_id": plan["items"][0]["sku_id"], "quantity": 2, "selected": True}]},
    )
    assert revision.status_code == 200, revision.json()
    assert revision.json()["selected_total_fen"] == 3600
    after = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()
    plan = after["plan"]
    confirmed = indexed_client.post(
        f"/api/v1/guide/tasks/{prepared['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": after["state_version"], "expected_session_version": after["session_version"],
              "selected_items": [{"sku_id": plan["items"][0]["sku_id"], "quantity": 2}]},
    )
    assert confirmed.status_code == 200, confirmed.json()
    cart = indexed_client.get("/api/v1/cart").json()
    assert [(i["sku_id"], i["quantity"]) for i in cart["items"]] == [("demo:cn-coke-original-330ml-6can", 2)]
    assert cart["total_price_fen"] == 3600

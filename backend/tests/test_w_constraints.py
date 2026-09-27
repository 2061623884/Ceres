"""W05 W08 combined constraints via /turns."""

from __future__ import annotations

import pytest

from support import post_turn


def _turn(client, sid, message, previous=None):
    previous = previous or {}
    resp = post_turn(client, sid, message, previous)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_w05_same_sentence_dish_people_budget_exclude(client, semantic_provider):
    """One sentence, four constraints — declared by the model, checked by the server.

    The model states what it heard (a dish, four people, a 500-yuan budget, no
    peanuts) in typed fields; the server still owns the prices and still enforces
    each of them. Nothing here is re-read from the sentence.
    """
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(
        lookup_then_add_id(
            "dish",
            "番茄炒蛋",
            "dish-fanqie-chao-dan",
            people=4,
            constraints={"budget_yuan": 500, "excluded_ingredients": ["peanut"]},
        )
    )
    sid = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]

    turn = _turn(client, sid, "番茄炒蛋4人预算500元不要花生")
    assert turn.get("plan"), turn
    assert turn["status"] == "awaiting_confirmation"
    assert "暂未收录" not in turn["message"]

    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    summary = session["constraints_summary"]
    assert summary.get("people") == 4
    assert summary.get("budget_fen") == 50000
    assert "peanut" in (summary.get("excluded_ingredients") or [])


def test_w08_first_turn_dish_with_budget_hits_template(client, semantic_provider):
    """A first-turn dish with a stated budget hits the real template.

    The budget is considered because the shopper states it, and the headcount is
    declared by the shopper too: a sentence that names no headcount is clarified
    (see the product rule), so this fixture states it rather than inventing one
    or leaning on a default.
    """
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(
        lookup_then_add_id(
            "dish",
            "番茄炒蛋",
            "dish-fanqie-chao-dan",
            people=2,
            constraints={"budget_yuan": 100},
        )
    )
    sid = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]

    turn = _turn(client, sid, "我想吃番茄炒蛋，2人，预算100元")
    assert turn.get("plan"), turn
    assert turn["status"] == "awaiting_confirmation"
    assert "暂未收录" not in turn["message"]
    assert turn["plan"]["total_price_fen"] <= 10000


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

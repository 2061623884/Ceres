"""Independent acceptance probes, not authored by the implementation agent.

The first probe used to assert a *server-side* refusal of a negative or
information-only sentence. That refusal lived in the retired tool gate
(``is_shopping_question`` / ``rejects_target``), which read the raw sentence with
regexes. The semantic chain has no such layer: whether "番茄炒蛋怎么做" is an
order or a question is the model's reading, and the server's job is to compile
what the model proposes against real data.

So the probe now asserts the contract that still holds, and that the retired
layer never was the point of: a turn that proposes no mutation leaves the plan
and the cart untouched, and a retrieval really happened first.

**Deliberately not asserted here**: that the *server* refuses a model which
insists on planning a rejected dish. It does not, by design — that is the
model's decision and is only verifiable against a real model (B3).
"""

from __future__ import annotations

import uuid

import pytest

from support import create_session, post_turn
from support.semantic_agent import lookup_then_reply
from app.services.shopping_plan_service import ShoppingPlanService


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


@pytest.mark.parametrize("message", [
    "不想吃番茄炒蛋",
    "番茄炒蛋怎么做",
])
def test_a_turn_without_a_mutation_plans_nothing_and_writes_no_cart(
    client, semantic_provider, message
):
    semantic_provider(lookup_then_reply("dish", "番茄炒蛋", "这道菜含鸡蛋和番茄，做法可以自己查。"))
    sid = create_session(client)

    result = turn(client, sid, message)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body.get("plan") is None, body
    assert body["plan_effect"] == "keep"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_shared_sku_contributions_survive_other_groups_and_rebuild(db_session):
    service = ShoppingPlanService(db_session)
    sku = "demo:eggs-fresh-6pack"

    def target(group, quantity):
        return {
            "plan_id": "test-plan",
            "plan_version": 1,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "target": {"group_id": group, "kind": "dish", "target_id": group, "name": group},
            "items": [{
                "sku_id": sku,
                "quantity": quantity,
                "recommended_quantity": quantity,
                "quantity_source": "recommended",
                "selected": True,
                "role": "required",
                "group_id": group,
            }],
        }

    first = service.merge_plan(None, target("dish:a", 1), group_id="dish:a", operation="append")
    second = service.merge_plan(first, target("dish:b", 2), group_id="dish:b", operation="append")
    assert second["items"][0]["quantity"] == 3
    repeated = service.merge_plan(second, target("dish:b", 2), group_id="dish:b", operation="append")
    assert repeated["items"][0]["quantity"] == 3, "Repeated target duplicated a shared SKU"
    resized = service.merge_plan(second, target("dish:a", 4), group_id="dish:a", operation="resize")
    assert resized["items"][0]["quantity"] == 6, "Resizing one dish lost the other dish's contribution"


def test_hand_edited_shared_sku_survives_append(db_session):
    service = ShoppingPlanService(db_session)
    base = {
        "plan_id": "test-plan",
        "plan_version": 1,
        "targets": [{"group_id": "dish:a", "kind": "dish", "target_id": "a"}],
        "items": [{
            "sku_id": "demo:eggs-fresh-6pack", "quantity": 3,
            "recommended_quantity": 1, "quantity_source": "user", "selected": True,
            "role": "required", "group_id": "dish:a",
        }],
    }
    new = {
        "plan_id": "new-plan",
        "target": {"group_id": "dish:b", "kind": "dish", "target_id": "b"},
        "items": [{
            "sku_id": "demo:eggs-fresh-6pack", "quantity": 1,
            "recommended_quantity": 1, "quantity_source": "recommended", "selected": True,
            "role": "required", "group_id": "dish:b",
        }],
    }
    merged = service.merge_plan(base, new, group_id="dish:b", operation="append")
    assert merged["items"][0]["quantity"] == 3, "Appending silently overwrote the user's chosen quantity"
    assert merged["items"][0]["quantity_source"] == "user"

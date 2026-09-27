"""P0 coverage consistency: one rule, every path, no drift.

The same plan read back from the build path, the session restore, a revision, a
refresh and a per-row add must report the same ``coverage_mode``/``can_confirm``,
and each of them must equal the shared pure rule (``plan_contract.coverage``).
"""

from __future__ import annotations

import uuid

import pytest

from app.services import plan_contract as contract
from support import post_turn


def create_session(client) -> str:
    return client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


def revise(client, body: dict, *, items=None, **extra):
    plan = body["plan"]
    payload = items if items is not None else [
        {
            "sku_id": row["sku_id"],
            "quantity": row["quantity"],
            "selected": row.get("selected", True),
        }
        for row in plan["items"]
    ]
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "client_edit_sequence": 1,
            "items": payload,
            **extra,
        },
    )


def _rule(plan: dict) -> dict:
    return contract.coverage(
        plan["items"], plan.get("gaps"), plan.get("coverage_intent") or contract.LEGACY_INTENT
    )


def _assert_same_rule(plan: dict) -> None:
    coverage = _rule(plan)
    assert plan["coverage_mode"] == coverage["coverage_mode"], plan
    assert plan["can_confirm"] == coverage["can_confirm"], plan
    assert list(plan.get("uncovered_items") or []) == coverage["uncovered_items"], plan


def _partial_dish(client, semantic_provider) -> dict:
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "三杯鸡", "dish-sanbei-ji", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃三杯鸡，2人").json()
    assert body["plan"] and body["plan"]["gaps"], body
    return body


def test_partial_plan_is_consistent_across_every_read_and_write_path(client, semantic_provider):
    body = _partial_dish(client, semantic_provider)
    plan = body["plan"]
    assert plan["coverage_mode"] == "partial", plan
    assert plan["coverage_intent"] == "partial_ok", plan
    assert plan["can_confirm"] is True, plan
    expected_ids = {gap["gap_id"] for gap in plan["gaps"]}
    _assert_same_rule(plan)

    # Session restore: the persisted plan must read back identically.
    restored = client.get(f"/api/v1/guide/sessions/{body['session_id']}").json()["plan"]
    assert restored["coverage_mode"] == plan["coverage_mode"], restored
    assert restored["can_confirm"] == plan["can_confirm"], restored
    assert restored["gaps"] == plan["gaps"], restored
    assert restored["coverage_intent"] == plan["coverage_intent"], restored
    _assert_same_rule(restored)

    # ``full`` never authorizes an incomplete confirmation: the plan is honestly
    # partial, but it is *not* confirmable until the caller allows partial_ok.
    strict = revise(client, body, coverage_intent="full").json()
    assert strict["coverage_mode"] == "partial", strict
    assert strict["coverage_intent"] == "full", strict
    assert strict["can_confirm"] is False, strict
    assert {gap["gap_id"] for gap in strict["gaps"]} == expected_ids, strict
    _assert_same_rule({**plan, **strict})

    # The client echoes the plan's own intent: confirmable again, same gaps.
    permissive = revise(
        client,
        {
            **body,
            "state_version": strict["state_version"],
            "session_version": strict["session_version"],
            "plan": {**plan, **strict},
        },
        coverage_intent=plan["coverage_intent"],
    ).json()
    assert permissive["coverage_mode"] == "partial", permissive
    assert permissive["can_confirm"] is True, permissive
    assert {gap["gap_id"] for gap in permissive["gaps"]} == expected_ids, permissive
    _assert_same_rule({**plan, **permissive})

    # A re-price (refresh) is not a downgrade: gaps survive and nothing is stale.
    refreshed_response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": permissive["session_version"],
            "expected_state_version": permissive["state_version"],
            "base_plan_id": permissive["plan_id"],
            "base_plan_version": permissive["plan_version"],
        },
    )
    assert refreshed_response.status_code == 200, refreshed_response.text
    refreshed = refreshed_response.json()
    assert refreshed["stale_items"] == [], refreshed
    assert refreshed["coverage_mode"] == "partial", refreshed
    assert refreshed["coverage_intent"] == "partial_ok", refreshed
    assert refreshed["can_confirm"] is True, refreshed
    assert {gap["gap_id"] for gap in refreshed["gaps"]} == expected_ids, refreshed
    _assert_same_rule(refreshed)


def test_row_add_keeps_gaps_and_never_re_arms_a_bought_row(client, semantic_provider):
    body = _partial_dish(client, semantic_provider)
    plan = body["plan"]
    row = next(row for row in plan["items"] if row.get("selected"))
    response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/items/{row['sku_id']}/add",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": row["quantity"],
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
        },
    )
    assert response.status_code == 200, response.text
    added = response.json()
    assert {gap["gap_id"] for gap in added["gaps"]} == {gap["gap_id"] for gap in plan["gaps"]}, added
    assert added["coverage_mode"] == "partial", added
    # One rule, plus the row-add path's own extra guard: a plan with nothing left
    # to buy is not re-armed for a second confirmation.
    coverage = contract.coverage(
        added["items"], added["gaps"], added["coverage_intent"]
    )
    assert added["coverage_mode"] == coverage["coverage_mode"], added
    assert added["can_confirm"] == (
        coverage["can_confirm"] and added["outstanding_total_fen"] > 0
    ), added


def test_deselection_is_uncovered_items_and_never_a_supply_gap(client, semantic_provider):
    """``uncovered_items`` projects the user's own untick; it is not a gap."""
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    plan = body["plan"]
    tomato = next(row for row in plan["items"] if "tomato" in row["sku_id"])
    edits = [
        {
            "sku_id": row["sku_id"],
            "quantity": row["quantity"],
            "selected": row["sku_id"] != tomato["sku_id"],
        }
        for row in plan["items"]
    ]

    strict = revise(client, body, items=edits, coverage_intent="full").json()
    assert strict["coverage_mode"] == "uncovered", strict
    assert strict["can_confirm"] is False, strict
    assert [row["sku_id"] for row in strict["uncovered_items"]] == [tomato["sku_id"]], strict
    assert strict["uncovered_items"][0]["required_item_id"] == tomato["required_item_id"], strict
    assert all(gap.get("sku_id") != tomato["sku_id"] for gap in strict["gaps"]), strict

    permissive = revise(
        client,
        {
            **body,
            "state_version": strict["state_version"],
            "session_version": strict["session_version"],
            "plan": {**body["plan"], **strict},
        },
        items=edits,
        coverage_intent="partial_ok",
    ).json()
    assert permissive.get("coverage_mode") == "partial", permissive
    assert permissive.get("can_confirm") is True, permissive
    assert [row["sku_id"] for row in permissive.get("uncovered_items") or []] == [tomato["sku_id"]], permissive


def test_refresh_uses_the_persisted_intent_not_the_coverage_result(client, semantic_provider):
    """A partial draft must not be silently downgraded by a re-price."""
    body = _partial_dish(client, semantic_provider)
    plan = body["plan"]
    assert plan["coverage_intent"] == "partial_ok", plan
    response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
        },
    )
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["coverage_intent"] == "partial_ok", refreshed
    assert refreshed["coverage_mode"] == "partial", refreshed


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    from app.llm import provider as llm_provider

    def _refuse(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("P0 coverage tests must not call a live model")

    monkeypatch.setattr(llm_provider, "get_semantic_provider", _refuse)

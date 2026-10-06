"""P0 gap persistence & every echo surface.

``gaps``/``coverage_intent`` (and the per-row requirement/evidence) must survive
``plan_json`` and reach every read surface the client uses: the turn response,
the session snapshot, ``plan.ready``, the revision response, the refresh response
and the per-row add response. A field that only exists in one of them is a silent
hole in the contract.
"""

from __future__ import annotations

import json
import uuid

import pytest

from support import post_turn
from support import stream_turn
from test_semantic_phase1_purchase import indexed_client


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


def turn_body(session_id: str, message: str, previous: dict | None = None) -> dict:
    previous = previous or {}
    return {
        "request_id": str(uuid.uuid4()),
        "message": message,
        "expected_task_id": previous.get("task_id"),
        "expected_state_version": previous.get("state_version", 0),
        "expected_session_version": previous.get("session_version"),
    }


def turn(client, session_id: str, message: str, previous: dict | None = None):
    return post_turn(client, session_id, message, previous)


def _partial_dish(client, semantic_provider) -> dict:
    from support.semantic_agent import lookup_then_add_id

    target = lookup_then_add_id(
        "dish", "酸汤肥牛", "dish-suantang-feiniu", people=2
    )[0]

    def opt_in(request):
        question = next(
            item for item in request["pending_clarifications"]
            if item["slot"] == "supply_gap_choice"
        )
        return {
            **target(request),
            "resolved_questions": [question["question_id"]],
        }

    semantic_provider([target, opt_in])
    sid = create_session(client)
    preview = turn(client, sid, "我想吃酸汤肥牛，2人").json()
    assert preview["plan"] is None and preview["task_id"] is None, preview
    assert preview["pending_clarifications"][0]["slot"] == "supply_gap_choice", preview
    assert client.get("/api/v1/cart").json()["items"] == []
    body = turn(client, sid, "那就先买能买到的", preview).json()
    plan = body["plan"]
    assert plan and plan["coverage_mode"] == "partial", body
    assert {gap["ingredient_id"] for gap in plan["gaps"]} == {"enoki_mushroom", "chili_sauce"}, plan
    enoki = next(gap for gap in plan["gaps"] if gap["ingredient_id"] == "enoki_mushroom")
    assert enoki["requiredness"] == "core", enoki
    chili = next(gap for gap in plan["gaps"] if gap["ingredient_id"] == "chili_sauce")
    assert chili["requiredness"] == "optional", chili
    assert chili["kind"] == "unknown" and chili["unknown_of"] == "quantity", chili
    beef_rows = [
        row for row in plan["items"]
        if row["requirement"]["ingredient_id"] == "beef_slice"
    ]
    assert len(beef_rows) == 1 and beef_rows[0]["availability"] == "available", beef_rows
    return body


def _task_plan(client, task_id: str) -> dict:
    from app.core import database as db_module
    from app.models.session import GuideTask

    db = db_module.SessionLocal()
    try:
        task = db.get(GuideTask, task_id)
        return json.loads(task.plan_json)
    finally:
        db.close()


def test_plan_json_persists_the_gap_and_the_requirement_evidence(indexed_client, semantic_provider):
    body = _partial_dish(indexed_client, semantic_provider)
    stored = _task_plan(indexed_client, body["task_id"])

    assert stored["coverage_intent"] == "partial_ok", stored
    assert stored["coverage_mode"] == "partial", stored
    enoki = next(g for g in stored["gaps"] if g["ingredient_id"] == "enoki_mushroom")
    for key in (
        "gap_id",
        "group_id",
        "target_kind",
        "target_id",
        "kind",
        "requiredness",
        "required_item_id",
        "ingredient_id",
        "name",
        "required_quantity",
        "unit",
        "quantity_known",
        "source",
        "message",
    ):
        assert key in enoki, (key, enoki)
    assert enoki["name"] == "金针菇", enoki
    assert enoki["source"] == {"kind": "local_recipe", "ref": "dish-suantang-feiniu"}, enoki
    assert enoki["required_item_id"] == "dish:dish-suantang-feiniu#enoki_mushroom", enoki

    for row in stored["items"]:
        assert row["required_item_id"], row
        assert row["requirement"]["quantity_known"] in (True, False), row
        assert row["evidence"]["quoted_at"], row
        assert row["evidence"]["stock_verified"] is True, row
        assert row["pack_source"] in ("catalog_spec", "assumed_one"), row

    # A supply gap is not the user's untick: the two lists never overlap.
    assert stored["uncovered_items"] == [], stored


def test_every_read_surface_echoes_gaps_and_intent(indexed_client, semantic_provider):
    client = indexed_client
    body = _partial_dish(client, semantic_provider)
    plan = body["plan"]
    expected_ids = {gap["gap_id"] for gap in plan["gaps"]}

    restored = client.get(f"/api/v1/guide/sessions/{body['session_id']}").json()["plan"]
    assert {gap["gap_id"] for gap in restored["gaps"]} == expected_ids, restored
    assert restored["coverage_intent"] == "partial_ok", restored

    revised = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": body["session_version"],
            "expected_state_version": body["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "client_edit_sequence": 1,
            "coverage_intent": plan["coverage_intent"],
            "items": [
                {
                    "sku_id": row["sku_id"],
                    "quantity": row["quantity"],
                    "selected": row.get("selected", True),
                }
                for row in plan["items"]
            ],
        },
    ).json()
    assert {gap["gap_id"] for gap in revised["gaps"]} == expected_ids, revised
    assert revised["coverage_intent"] == "partial_ok", revised

    refreshed = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": revised["session_version"],
            "expected_state_version": revised["state_version"],
            "base_plan_id": revised["plan_id"],
            "base_plan_version": revised["plan_version"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    refreshed_body = refreshed.json()
    assert {gap["gap_id"] for gap in refreshed_body["gaps"]} == expected_ids, refreshed_body
    assert refreshed_body["coverage_intent"] == "partial_ok", refreshed_body

    row = next(row for row in refreshed_body["items"] if row.get("selected"))
    added = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/items/{row['sku_id']}/add",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": row["quantity"],
            "expected_state_version": refreshed_body["state_version"],
            "expected_session_version": refreshed_body["session_version"],
        },
    )
    assert added.status_code == 200, added.text
    added_body = added.json()
    assert {gap["gap_id"] for gap in added_body["gaps"]} == expected_ids, added_body
    assert added_body["coverage_intent"] == "partial_ok", added_body


def test_plan_ready_sse_carries_the_same_gaps(indexed_client, semantic_provider):
    from support.semantic_agent import lookup_then_add_id

    target = lookup_then_add_id(
        "dish", "酸汤肥牛", "dish-suantang-feiniu", people=2
    )[0]

    def opt_in(request):
        question = next(
            item for item in request["pending_clarifications"]
            if item["slot"] == "supply_gap_choice"
        )
        return {
            **target(request),
            "resolved_questions": [question["question_id"]],
        }

    semantic_provider([target, opt_in])
    client = indexed_client
    sid = create_session(client)
    preview_events = stream_turn(client, sid, "我想吃酸汤肥牛，2人")
    preview = next(event["payload"] for event in preview_events if event["type"] == "turn.completed")
    assert preview["plan"] is None and preview["task_id"] is None, preview
    assert preview["pending_clarifications"][0]["slot"] == "supply_gap_choice", preview
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{sid}/turns/stream",
        json=turn_body(sid, "那就先买能买到的", preview),
    ) as response:
        assert response.status_code == 200, response.read()
        events = [
            json.loads(chunk.removeprefix("data: "))
            for chunk in "".join(response.iter_text()).split("\n\n")
            if chunk.startswith("data:")
        ]
    ready = next(event for event in events if event["type"] == "plan.ready")
    ready_plan = ready["payload"]["plan"]
    assert ready_plan["coverage_mode"] == "partial", ready_plan
    assert ready_plan["coverage_intent"] == "partial_ok", ready_plan
    assert any(gap["ingredient_id"] == "enoki_mushroom" for gap in ready_plan["gaps"]), ready_plan

    completed = next(event for event in events if event["type"] == "turn.completed")
    terminal_plan = completed["payload"]["plan"]
    assert terminal_plan["gaps"] == ready_plan["gaps"], (terminal_plan, ready_plan)


def test_the_reply_names_the_missing_main_ingredient(indexed_client, semantic_provider):
    """D3: the shortage is stated in words the shopper reads, not just in fields."""
    body = _partial_dish(indexed_client, semantic_provider)
    message = body["message"]
    assert "金针菇" in message, message
    assert "无法配齐" in message, message
    # The sentence is the structured gap's own wording (server-composed), and
    # money stays in yuan — the internal fen amount never leaks into prose.
    gap_text = next(
        gap["message"] for gap in body["plan"]["gaps"] if gap["ingredient_id"] == "enoki_mushroom"
    )
    assert gap_text in message, message
    assert "fen" not in message, message
    assert str(body["plan"]["selected_total_fen"]) not in message, message


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    from app.llm import provider as llm_provider

    def _refuse(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("P0 gap-persistence tests must not call a live model")

    monkeypatch.setattr(llm_provider, "get_semantic_provider", _refuse)

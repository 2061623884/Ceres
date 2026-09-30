"""Offline regression evidence for the semantic turn.

Every test here runs the real one chain — loop, read port, plan-change executor,
business services and database. Only the *model* is scripted, so no credentials
and no network are involved.

Two blocks of the retired suite had no subject left and are retired with their
subject: the tool-call budget ("each requested call is
answered, including the rejected one") and the gate's strict *argument shape*
check. The structural check itself still exists — it moved to the shared
validator and is covered by ``test_agent_tools.py``; the model-call budget is
covered by ``test_agent_loop.py``.

The constraints block changed meaning on purpose: the retired chain let the model
omit a budget and had the *server* re-fill it from the raw sentence. There is no
sentence reading any more, so the equivalent contract is "the model declares the
budget it heard, and the server still enforces it against real prices".
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from support import create_session, post_turn, post_turn
from support.semantic_agent import (
    lookup_then_add,
    lookup_then_add_id,
    lookup_then_reply,
    reply_only,
)

TOMATO = "dish-fanqie-chao-dan"
QINGJIAO_ROUSI = "dish-qingjiao-rousi"
GONGBAO = "dish-gongbao-jiding"


def turn(
    client,
    session_id: str,
    message: str,
    *,
    request_id: str | None = None,
    task_id: str | None = None,
    state_version: int = 0,
    session_version: int | None = None,
):
    previous = {"task_id": task_id, "state_version": state_version}
    if session_version is not None:
        previous["session_version"] = session_version
    return post_turn(
        client, session_id, message, previous, request_id=request_id
    )


def _db_for(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def count_rows(client, table: str) -> int:
    db = _db_for(client)
    try:
        return int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    finally:
        db.close()


# --------------------------------------------------------------------- core loop


def test_a_verified_target_is_retrieved_and_committed_in_one_turn(
    client, semantic_provider
):
    """Name the target and look it up in one call; the server binds the exact hit."""
    provider = semantic_provider(
        lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2)
    )
    sid = create_session(client)
    resp = turn(client, sid, "我想吃番茄炒蛋，2人")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["plan"], body
    assert body["plan"]["plan_id"]
    assert body["plan_effect"] == "replace"
    assert body["plan"]["targets"][0]["target_id"] == TOMATO
    assert body["task_id"], "a task is created lazily when a real plan exists"

    # One model call: the write never waits for a second model round.
    assert len(provider.requests) == 1, provider.requests
    assert provider.requests[0].get("query_results") in (None, [])


def test_the_api_plan_surface_keeps_every_declared_field(client, semantic_provider):
    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    items = body["plan"]["items"]
    assert items
    for item in items:
        assert item["sku_id"]
        assert item["image_path"] is not None, item
        assert item["spec_quantity"] is not None
        assert item["spec_unit"]
        assert item["max_addable_quantity"] is not None
        assert item["recommended_quantity"] >= 1


def test_direct_conversation_creates_no_task(client, semantic_provider):
    provider = semantic_provider([reply_only("你好，想吃什么菜？可以告诉我人数和预算。")])
    sid = create_session(client)
    before = count_rows(client, "guide_tasks")
    resp = turn(client, sid, "你好")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["task_id"] is None
    assert body["plan"] is None
    assert body["plan_effect"] == "keep"
    assert body["message"].startswith("你好")
    assert count_rows(client, "guide_tasks") == before
    assert len(provider.requests) == 1, "plain chat is one model call"


# ------------------------------------------------- candidate set and selection


def test_an_open_question_and_its_real_options_survive_a_reload(
    client, semantic_provider
):
    """The question and the refs it offered are stored, not kept in memory."""

    # 「青椒」 names no dish exactly: the server offers the similar real dishes.
    semantic_provider(lookup_then_add("dish", "青椒"))
    sid = create_session(client)
    body = turn(client, sid, "我想做个青椒的菜").json()

    assert body["plan"] is None, "an open question must not auto-select a dish"
    pending = body["pending_clarifications"]
    assert pending, body
    options = pending[0].get("options") or []
    assert len(options) >= 2, pending
    assert all(option.get("label") for option in options), options

    # Reload from storage: no purchase task exists, and the question is still there.
    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session["task_id"] is None
    stored = session["pending_clarifications"]
    assert stored, "the question must be durable, not turn-local"
    assert stored[0]["question"] == pending[0]["question"]


def test_choosing_a_dish_after_the_question_creates_the_purchase_task(
    client, semantic_provider
):
    semantic_provider(
        lookup_then_reply("dish", "青椒", "你想吃哪一道？青椒肉丝还是别的？")
    )
    sid = create_session(client)
    first = turn(client, sid, "我想做个青椒的菜").json()
    assert first["plan"] is None

    semantic_provider(lookup_then_add_id("dish", "青椒肉丝", QINGJIAO_ROUSI, people=2))
    second = turn(client, sid, "青椒肉丝，两人吃", task_id=first["task_id"]).json()

    assert second["plan"], second
    assert second["task_id"], "choosing creates the purchase task"
    assert second["plan"]["targets"][0]["target_id"] == QINGJIAO_ROUSI


def test_a_ref_this_turn_never_issued_cannot_be_prepared(client, semantic_provider):
    """A ref the server did not issue this turn is refused, not guessed at.

    The proposal is otherwise valid — a declared buy target with the user's own
    headcount — so the auth path is reached and it is the *forged reference*
    that is refused (UNKNOWN_CANDIDATE_REF), with zero write.
    """
    semantic_provider(
        [
            {
                "target": {
                    "kind": "meal",
                    "name": "青椒肉丝",
                    "intent": "buy",
                    "ref": "d0000000000forged",
                },
                "constraints": {"people": 2, "fulfillment_mode": "self_cook"},
            }
        ]
    )
    sid = create_session(client)
    body = turn(client, sid, "我想做个青椒肉丝，2人").json()

    assert body["plan"] is None, "an unissued ref must not become a plan"
    codes = [r.get("code") for r in body["action_results"]]
    assert "UNKNOWN_CANDIDATE_REF" in codes, body["action_results"]


# ------------------------------------------------------------ stated constraints
#
# The model states what it heard in typed fields; the server still owns every
# price, pack size and stock number and still refuses an over-budget plan. There
# is no server-side re-reading of the sentence to fill in a budget the model
# omitted — that was the retired chain's job, and it is gone by design.


def _codes(body: dict) -> list:
    return [r.get("code") for r in body.get("action_results") or []]


def test_a_declared_budget_is_enforced_against_real_prices(client, semantic_provider):
    semantic_provider(
        lookup_then_add_id(
            "dish", "番茄炒蛋", TOMATO, people=2, constraints={"budget_yuan": 10}
        )
    )
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人，预算10元").json()

    assert body["plan"] is None, body
    assert "BUDGET_EXCEEDED" in _codes(body), body["action_results"]
    assert body["plan_effect"] == "keep"


def test_a_generous_declared_budget_still_produces_a_plan(client, semantic_provider):
    semantic_provider(
        lookup_then_add_id(
            "dish", "番茄炒蛋", TOMATO, people=2, constraints={"budget_yuan": 100}
        )
    )
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人，预算100元").json()

    assert body["plan"], body
    assert body["plan"]["total_price_fen"] <= 10000


def test_a_declared_exclusion_is_enforced_by_the_planner(client, semantic_provider):
    semantic_provider(
        lookup_then_add_id(
            "dish",
            "宫保鸡丁",
            GONGBAO,
            people=2,
            constraints={"excluded_ingredients": ["peanut"]},
        )
    )
    sid = create_session(client)
    body = turn(client, sid, "想吃宫保鸡丁，2人，不要花生").json()

    assert body["plan"] is None, "a declared exclusion must not be dropped"
    failures = [r for r in body["action_results"] if r.get("status") == "failed"]
    assert failures, body["action_results"]
    assert failures[0].get("message"), failures[0]


# --------------------------------------------------------- cart write boundary


def _confirm(client, body):
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": body["plan"]["plan_id"],
            "plan_version": body["plan"]["plan_version"],
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
            "selected_items": [
                {"sku_id": i["sku_id"], "quantity": i["quantity"]}
                for i in body["plan"]["items"]
                if i.get("selected", True)
            ],
        },
    )


def test_no_cart_write_before_confirmation(client, semantic_provider):
    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    assert client.get("/api/v1/cart").json()["items"] == []
    assert body["available_actions"] is not None

    confirm = _confirm(client, body)
    assert confirm.status_code == 200, confirm.text
    assert client.get("/api/v1/cart").json()["items"]


# --------------------------------------------------- completed task immutability


def test_completed_task_is_readonly_and_a_new_purchase_gets_a_new_task(
    client, semantic_provider
):
    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2))
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    assert _confirm(client, first).status_code == 200

    db = _db_for(client)
    snapshot_before = db.execute(
        text("SELECT plan_json, user_confirmed, cart_result_json FROM guide_tasks WHERE task_id = :t"),
        {"t": first["task_id"]},
    ).fetchone()

    semantic_provider([reply_only("刚才加入了 2 件番茄炒蛋的用料。")])
    readonly = turn(
        client,
        sid,
        "刚才买了什么？",
        task_id=first["task_id"],
        state_version=first["state_version"] + 1,
    ).json()
    assert readonly["task_id"] == first["task_id"]
    assert readonly["plan_effect"] == "keep"

    db.expire_all()
    snapshot_after = db.execute(
        text("SELECT plan_json, user_confirmed, cart_result_json FROM guide_tasks WHERE task_id = :t"),
        {"t": first["task_id"]},
    ).fetchone()
    assert snapshot_after == snapshot_before, "a readonly question must not rewrite history"

    semantic_provider(
        lookup_then_add_id("dish", "青椒肉丝", QINGJIAO_ROUSI, people=4)
    )
    second = turn(
        client,
        sid,
        "我还想吃青椒肉丝，4人",
        task_id=first["task_id"],
        state_version=readonly["state_version"],
    ).json()
    assert second["task_id"] != first["task_id"]
    assert second["plan"], second


def test_purchase_summary_uses_items_added_and_marks_unknown_totals(
    client, semantic_provider
):
    semantic_provider(lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2))
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    assert _confirm(client, body).status_code == 200

    from app.agent.context_resolver import ContextResolver

    db = _db_for(client)
    owner_id = str(
        db.execute(text("SELECT owner_id FROM guide_sessions LIMIT 1")).scalar()
    )
    ctx = ContextResolver(db, owner_id).resolve(sid)
    summary = ctx.purchase_summary
    assert summary is not None
    assert summary["source"] == "cart_result"
    assert summary["items"], summary
    for item in summary["items"]:
        assert item["sku_id"]
        assert item["quantity"] >= 1
    # The cart write only records sku_id + quantity; names come from the plan.
    assert any(item.get("name") for item in summary["items"])
    assert summary["total_fen"] is not None
    assert summary["total_fen"] > 0

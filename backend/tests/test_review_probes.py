"""M0 review probes migrated from audit (assertions adapted, phrases unchanged)."""

from __future__ import annotations

import pytest

import json
from typing import get_args
from uuid import uuid4

from app.schemas.guide import AnswerStatus, Step
from support import post_turn


def turn(client, sid, message, previous=None):
    previous = previous or {}
    response = post_turn(client, sid, message, previous, request_id=str(uuid4()))
    assert response.status_code == 200, response.text
    return response.json()


def plan(client, message="我想吃番茄炒蛋"):
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
    result = turn(client, sid, message)
    assert result.get("plan"), result
    return result


def edits(first):
    return [
        {
            "sku_id": item["sku_id"],
            "quantity": item["quantity"],
            "selected": item.get("selected", item.get("role") != "pantry"),
        }
        for item in first["plan"]["items"]
    ]


def revision_body(first, items, **extra):
    return {
        "request_id": str(uuid4()),
        "expected_session_version": first["session_version"],
        "expected_state_version": first["state_version"],
        "base_plan_id": first["plan"]["plan_id"],
        "base_plan_version": first["plan"]["plan_version"],
        "client_edit_sequence": 1,
        "items": items,
        **extra,
    }


def revise(client, first, items, **extra):
    response = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/plan-revisions",
        json=revision_body(first, items, **extra),
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, first, revision=None, key=None):
    current = revision or {
        **first["plan"],
        **{k: first[k] for k in ("state_version", "session_version")},
    }
    items = current["items"] if isinstance(current.get("items"), list) else first["plan"]["items"]
    return client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "plan_id": current["plan_id"],
            "plan_version": current["plan_version"],
            "expected_state_version": current["state_version"],
            "expected_session_version": current["session_version"],
            "selected_items": [
                {"sku_id": i["sku_id"], "quantity": i["quantity"]}
                for i in items
                if i.get("selected", i.get("role") != "pantry")
            ],
        },
    )


def _cart_snapshot(client):
    cart = client.get("/api/v1/cart").json()
    return cart.get("version"), json.dumps(cart.get("items", []), sort_keys=True)


def test_review_revision_replay_before_version_check(client):
    first = plan(client)
    body = revision_body(first, edits(first))
    endpoint = f"/api/v1/guide/tasks/{first['task_id']}/plan-revisions"
    original = client.post(endpoint, json=body)
    replay = client.post(endpoint, json=body)
    assert original.status_code == 200, original.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == original.json()


def test_review_cannot_confirm_missing_required_material(client):
    first = plan(client)
    cart_version_before, cart_items_before = _cart_snapshot(client)
    items = edits(first)
    next(i for i in items if "tomato" in i["sku_id"])["selected"] = False
    revised = revise(client, first, items)
    assert revised["can_confirm"] is False, revised
    result = confirm(client, first, revised)
    cart_version_after, cart_items_after = _cart_snapshot(client)
    assert result.status_code >= 400, {"confirm": result.json(), "cart": client.get("/api/v1/cart").json()}
    assert cart_version_after == cart_version_before
    assert cart_items_after == cart_items_before


def test_review_partial_purchase_must_not_claim_full_coverage(client):
    first = plan(client)
    items = edits(first)
    next(i for i in items if "tomato" in i["sku_id"])["selected"] = False
    revised = revise(client, first, items, coverage_intent="partial_ok")
    assert revised["coverage_mode"] == "partial", revised
    assert revised["uncovered_items"], revised


def test_review_self_supplied_requires_specific_materials(client):
    first = plan(client)
    items = edits(first)
    next(i for i in items if "tomato" in i["sku_id"])["selected"] = False
    revised = revise(
        client, first, items, coverage_intent="user_supplied", user_supplied_ingredients=[]
    )
    assert revised["can_confirm"] is False, revised


def test_review_revision_cannot_bypass_hard_budget(client, semantic_provider):
    """The budget is stated when the plan is built, not patched onto it later.

    Rewriting a live plan's budget is not a supported operation in the one chain,
    so the probe states it in the same turn that builds the plan and then goes
    after the revision API — which is what this probe is actually about.
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
    first = turn(client, sid, "我想吃番茄炒蛋，2人，预算100元")
    assert first.get("plan"), first
    state = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert state["constraints_summary"]["budget_fen"] == 10000, state
    assert first["plan"]["total_price_fen"] <= 10000, first
    cart_version_before, cart_items_before = _cart_snapshot(client)
    items = edits(first)
    next(i for i in items if "tomato" in i["sku_id"])["quantity"] = 20
    revised = revise(client, first, items)
    assert revised["selected_total_fen"] > 10000, revised
    result = confirm(client, first, revised)
    cart_version_after, cart_items_after = _cart_snapshot(client)
    assert not revised["can_confirm"] and result.status_code >= 400, {
        "budget_fen": 10000,
        "selected_total_fen": revised["selected_total_fen"],
        "can_confirm": revised["can_confirm"],
        "confirm_status": result.status_code,
        "cart": client.get("/api/v1/cart").json(),
    }
    assert cart_version_after == cart_version_before
    assert cart_items_after == cart_items_before


def test_review_revision_refreshes_current_offer_price(client):
    from app.core.database import SessionLocal
    from app.models.store import Offer

    first = plan(client)
    tomato = next(i for i in first["plan"]["items"] if "tomato" in i["sku_id"])
    with SessionLocal() as db:
        offer = db.query(Offer).filter_by(store_id="store-demo-01", sku_id=tomato["sku_id"]).one()
        offer.price_fen += 100
        expected_price = offer.price_fen
        db.commit()
    revised = revise(client, first, edits(first))
    actual_price = next(i["unit_price_fen"] for i in revised["items"] if i["sku_id"] == tomato["sku_id"])
    assert actual_price == expected_price, {
        "expected_current_price": expected_price,
        "actual_revision_price": actual_price,
        "confirm": confirm(client, first, revised).json(),
    }


def test_review_confirm_is_queryable_by_request_id(client):
    first = plan(client)
    key = str(uuid4())
    result = confirm(client, first, key=key)
    assert result.status_code == 200, result.text
    lookup = client.get(
        "/api/v1/guide/operations",
        params={"op_type": "confirm", "request_id": key},
    ).json()
    assert len(lookup["operations"]) == 1, {"confirm": result.json(), "lookup": lookup}


def test_review_confirm_result_is_durable_conversation_message(client):
    first = plan(client)
    result = confirm(client, first)
    assert result.status_code == 200, result.text
    messages = client.get(f"/api/v1/guide/sessions/{first['session_id']}/messages").json()["messages"]
    assert any(m["kind"] == "action_result" for m in messages), messages


def test_review_cancel_returns_committed_version(client):
    first = plan(client)
    result = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/cancel",
        json={
            "request_id": str(uuid4()),
            "expected_session_version": first["session_version"],
            "expected_state_version": first["state_version"],
        },
    )
    assert result.status_code == 200, result.text
    state = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()
    assert result.json()["state_version"] == state["state_version"], {
        "cancel": result.json(),
        "stored": state["state_version"],
    }


def test_review_completed_people_change_requires_scope_clarification(client, semantic_provider):
    """After a completed task, "改成四人份" does not name the scope.

    The headcount change on a finished list is ambiguous: append to what was
    bought, or make a separate new list. That is a question the *model* states in
    the real proposal protocol (an uncertainty with its own wording), not a
    server keyword rule; the turn must surface it and change nothing until the
    shopper answers. The scripted provider stands in for that model reading
    only - the parse/decide/execute/HTTP chain below is the real one.

    An older assertion required the top-level ``status`` to read "clarifying",
    which conflated the task's own step with the answer's clarification. The
    finished task must stay ``completed``; the open question is asserted where
    it really lives (``pending_clarification`` / the clarification receipt), and
    a replay of the same request must not reopen the task.
    """
    from support.semantic_agent import lookup_then_add_id

    def ask_scope(request):
        return {
            "reply": "这份清单已经确认过了，我先确认一下你要怎么改。",
            "questions": [
                {
                    "slot": "gap_fill_scope",
                    "question": "是在已购清单上追加，还是另做一份新清单？",
                }
            ],
        }

    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2),
            ask_scope,
        ]
    )
    first = plan(client)
    result = confirm(client, first)
    assert result.status_code == 200, result.text
    confirmed = result.json()
    cart_before = _cart_snapshot(client)

    request_id = str(uuid4())
    body = {
        "request_id": request_id,
        "message": "改成四人份",
        "expected_task_id": confirmed["task_id"],
        "expected_state_version": confirmed["state_version"],
        "expected_session_version": confirmed["session_version"],
    }
    following = post_turn(
        client,
        first["session_id"],
        body["message"],
        confirmed,
        request_id=request_id,
    ).json()

    # The task status and the answer's clarification are different fields. A
    # finished task stays finished (``status`` is the task step, the single
    # source for which is app/schemas/guide.Step); the open question is carried
    # by ``pending_clarification`` and the clarification receipt. The response
    # never labels a finished task as a task-step "clarifying", and nothing of
    # the finished work is rewritten.
    assert following["status"] == "completed", following
    assert following["status"] in get_args(Step), following["status"]
    # "completed" is not an AnswerStatus, so the answer field falls back exactly
    # as app/agent/responses.py documents; the clarification is not smuggled into
    # it as a task step.
    assert following["answer_status"] in get_args(AnswerStatus), following["answer_status"]
    assert following["answer_status"] == "accepted", following["answer_status"]
    assert following.get("plan") is None, following.get("plan")
    assert following.get("plan_effect") == "keep", following.get("plan_effect")

    pending = following.get("pending_clarification") or {}
    assert pending.get("slot") == "gap_fill_scope", pending
    assert pending.get("question"), pending
    assert any(
        r.get("type") == "clarification"
        and r.get("slot") == "gap_fill_scope"
        and r.get("status") == "needs_clarification"
        for r in following.get("action_results") or []
    ), following.get("action_results")

    # The finished task, its plan, its version and the cart are facts this turn
    # may not rewrite, and the question it asked is the question that is stored.
    state = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()
    assert state["task_id"] == first["task_id"]
    assert state["task_status"] == "completed", state["task_status"]
    assert state["state_version"] == confirmed["state_version"], state["state_version"]
    assert state["plan"] == first["plan"]
    assert len(state["pending_clarifications"]) == 1, state["pending_clarifications"]
    stored = state["pending_clarifications"][0]
    assert stored["question_id"] == pending["question_id"], (stored, pending)
    assert stored["question"] == pending["question"], (stored, pending)
    assert _cart_snapshot(client) == cart_before

    # Replaying the same request returns the same receipt on the same finished
    # task: a replay is neither a reason nor a second chance to reopen a
    # completed task.
    replay = post_turn(
        client,
        first["session_id"],
        body["message"],
        confirmed,
        request_id=request_id,
    )
    assert replay.status_code == 200, replay.text
    replayed = replay.json()
    assert replayed["task_id"] == confirmed["task_id"], replayed["task_id"]
    assert replayed["status"] == "completed", replayed
    assert replayed["message"] == following["message"], (replayed, following)
    assert replayed["assistant_message_id"] == following["assistant_message_id"]
    assert replayed["pending_clarification"]["question_id"] == pending["question_id"]
    after = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()
    assert after["task_id"] == first["task_id"]
    assert after["task_status"] == "completed", after["task_status"]
    assert after["state_version"] == confirmed["state_version"], after["state_version"]
    assert after["plan"] == first["plan"]
    assert _cart_snapshot(client) == cart_before


def test_review_combined_people_and_budget_does_not_drop_budget(client, semantic_provider):
    """A stated budget is either applied or explicitly refused - never dropped.

    The shopper states people and a budget together on a live plan. The budget
    participates: the turn either commits a plan that really fits the stated
    budget, or refuses the edit outright without partially applying the
    people/budget change.
    """
    from support.semantic_agent import lookup_then_add_id, request_amend

    def change_people_and_budget(request):
        group = request["current_plan"]["groups"][0]
        return {
            "reply": "人数和预算我记下了。",
            **request_amend(
                focus=group["ref"],
                name=group["name"],
                changes={"set": {"people": 2, "budget_yuan": 10}},
            ),
        }

    semantic_provider(
        [
            *lookup_then_add_id(
                "dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2
            ),
            change_people_and_budget,
        ]
    )
    first = plan(client)
    state_before = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()
    cart_before = _cart_snapshot(client)
    following = turn(client, first["session_id"], "改为两人份，预算10元", first)
    state = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()

    applied = (
        following.get("plan") is not None
        and following["plan"].get("total_price_fen") is not None
        and following["plan"]["total_price_fen"] <= 1000
    )
    if applied:
        assert state["constraints_summary"]["budget_fen"] == 1000, {
            "turn": following,
            "constraints": state["constraints_summary"],
        }
    else:
        codes = {
            r.get("code")
            for r in following.get("action_results") or []
            if r.get("saved") is not True
        }
        assert codes & {
            "UNSUPPORTED_OPERATION",
            "UNSUPPORTED_CHANGE_FIELD",
            "BUDGET_EXCEEDED",
            "GOAL_CHANGE_CONFLICT",
        }, following["action_results"]
        assert following.get("plan_effect") == "keep", following
        assert state["state_version"] == state_before["state_version"], state
        assert state["constraints_summary"] == state_before["constraints_summary"], {
            "turn": following,
            "constraints": state["constraints_summary"],
        }
        assert state["plan"] == state_before["plan"], state["plan"]
        assert _cart_snapshot(client) == cart_before


def test_review_stale_supply_plan_must_be_revalidated(client):
    from app.core.database import SessionLocal
    from app.models.store import DeliveryQuote

    first = plan(client)
    cart_version_before, cart_items_before = _cart_snapshot(client)
    with SessionLocal() as db:
        db.add(DeliveryQuote(store_id="store-demo-01", zone_id="zone-review", reachable=True))
        db.commit()
    updated = client.post(
        f"/api/v1/guide/sessions/{first['session_id']}/supply-context",
        json={
            "request_id": str(uuid4()),
            "expected_session_version": first["session_version"],
            "store_id": "store-demo-01",
            "delivery_zone_id": "zone-review",
        },
    )
    assert updated.status_code == 200, updated.text
    first["session_version"] = updated.json()["session_version"]
    state = client.get(f"/api/v1/guide/sessions/{first['session_id']}").json()
    assert state["plan"]["validation_status"] == "stale_supply", state
    result = confirm(client, first)
    cart_version_after, cart_items_after = _cart_snapshot(client)
    assert result.status_code >= 400, result.text
    assert cart_version_after == cart_version_before
    assert cart_items_after == cart_items_before


def test_review_xiaochaorou_is_not_qingjiao_rousi(client):
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    first = plan(client)
    following = turn(client, first["session_id"], "换成小炒肉", first)
    with SessionLocal() as db:
        task = db.get(GuideTask, following["task_id"])
        assert task.active_template_id != "dish-qingjiao-rousi", {
            "active_template_id": task.active_template_id,
            "requirements": json.loads(task.requirements_json),
            "turn": following,
        }


def test_review_product_image_is_actually_served(client):
    first = plan(client)
    tomato = next(i for i in first["plan"]["items"] if "tomato" in i["sku_id"])
    filename = tomato["image_path"].split("/")[-1]
    response = client.get(f"/media/images/{filename}")
    assert response.status_code == 200, {
        "image_path": tomato["image_path"],
        "status": response.status_code,
    }
    assert response.headers["content-type"].startswith("image/")


def test_review_named_dish_plus_budget_is_not_unsupported(client, semantic_provider):
    """A named dish plus a stated budget builds a plan that honours the budget."""
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
    result = plan(client, "我想吃番茄炒蛋，预算100元")
    assert result["status"] == "awaiting_confirmation", result
    state = client.get(f"/api/v1/guide/sessions/{result['session_id']}").json()
    assert state["constraints_summary"]["budget_fen"] == 10000, state["constraints_summary"]
    assert result["plan"]["total_price_fen"] <= 10000, result


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

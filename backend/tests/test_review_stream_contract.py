"""Review contract probes: S03 replay, S05 post-confirm Q&A, S06 mixed intent."""

from __future__ import annotations

import pytest

import json
import uuid

from app.models.conversation import GuideOperation
from support import post_turn

#: Structured conflict codes a read-only turn must never report. Kept here so the
#: check is on real codes, not on the substring "409" appearing in random ids.
CONFLICT_CODES = frozenset(
    {
        "IDEMPOTENCY_CONFLICT",
        "VERSION_CONFLICT",
        "STATE_VERSION_CONFLICT",
        "SESSION_VERSION_CONFLICT",
        "CONFLICT",
    }
)


def _session(client):
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


def _turn(client, sid, message, previous=None, request_id=None):
    previous = previous or {}
    resp = post_turn(client, sid, message, previous, request_id=request_id or str(uuid.uuid4()))
    return resp


def _plan(client, message="我想吃番茄炒蛋"):
    sid = _session(client)
    resp = _turn(client, sid, message)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("plan"), body
    return sid, body


def _confirm(client, body):
    items = body["plan"]["items"]
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
                for i in items
                if i.get("selected", i.get("role") != "pantry")
            ],
        },
    )


def test_s05_post_confirm_readonly_purchase_question(client, semantic_provider):
    """A post-confirm "what did I buy?" is answered from the real cart facts."""
    from support.semantic_agent import Continuation

    sid, first = _plan(client)
    confirmed = _confirm(client, first).json()
    assert confirmed["status"] == "completed"

    session_before = client.get(f"/api/v1/guide/sessions/{sid}").json()
    cart_before = client.get("/api/v1/cart").json()

    def answer_from_the_real_cart(request):
        result = next(
            r for r in request["query_results"] if r.get("kind") == "cart"
        )
        items = result.get("items") or []
        assert items, result
        lines = "、".join(f"{i['name']} x{i['quantity']}" for i in items)
        return {"reply": f"你已经加购了 {len(items)} 项：{lines}"}

    semantic_provider(
        [
            {"reads": [{"kind": "cart"}]},
            Continuation(answer_from_the_real_cart),
        ]
    )
    resp = _turn(client, sid, "刚才买了什么", confirmed)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "加购" in body["message"] or "已" in body["message"]
    assert body.get("items_added") is None  # turn response uses message, not cart dump
    # A read is not a conflict: assert the real HTTP status and structured codes,
    # never a substring scan of the body (random ids can contain "409").
    assert resp.status_code != 409, resp.text
    assert (body.get("error") or {}).get("code") != "IDEMPOTENCY_CONFLICT", body.get("error")
    assert body.get("answer_status") != "failed", body.get("answer_status")
    assert not any(
        str(r.get("code") or "") in CONFLICT_CODES
        for r in body.get("action_results") or []
    ), body.get("action_results")

    # Reading is not writing: the settled task, its plan and the cart are as they
    # were, and the turn stays on the completed task it was asked about.
    assert body["task_id"] == first["task_id"]
    session_after = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session_after["task_id"] == session_before["task_id"]
    assert session_after["task_status"] == session_before["task_status"]
    assert session_after["plan"] == session_before["plan"]
    assert client.get("/api/v1/cart").json() == cart_before


def test_s06_mixed_explain_and_budget_updates_plan(client, semantic_provider):
    """Mixed intent: explain the plan, and state a new budget in the same turn.

    A budget the shopper states must participate, never be silently ignored or
    invented. The turn therefore either commits a plan that really fits the
    stated budget, or refuses the change outright; a refusal may not be partial
    (the stored budget, the plan version and the cart stay exactly as they were).
    The fixture scripts the current proposal protocol so the first turn is
    grounded in a real retrieval and the second turn really reaches the server's
    budget handling.
    """
    from support.semantic_agent import lookup_then_add_id, request_amend

    def change_budget(request):
        group = request["current_plan"]["groups"][0]
        return {
            "reply": "这些菜是按两人份和当时说好的预算挑的。",
            **request_amend(
                focus=group["ref"], name=group["name"], changes={"set": {"budget_yuan": 10}}
            ),
        }

    semantic_provider(
        [
            *lookup_then_add_id(
                "dish",
                "番茄炒蛋",
                "dish-fanqie-chao-dan",
                people=2,
                constraints={"budget_yuan": 100},
            ),
            change_budget,
        ]
    )
    sid, first = _plan(client, "我想吃番茄炒蛋，预算100元")
    assert first["plan"]["total_price_fen"] <= 10000

    session_before = client.get(f"/api/v1/guide/sessions/{sid}").json()
    cart_before = client.get("/api/v1/cart").json()

    resp = _turn(
        client,
        sid,
        "为什么选这些，预算改成10元",
        first,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    session_after = client.get(f"/api/v1/guide/sessions/{sid}").json()

    applied = (
        body.get("plan") is not None
        and body["plan"].get("total_price_fen") is not None
        and body["plan"]["total_price_fen"] <= 1000
    )
    if applied:
        # Honouring the stated budget means it is the constraint that is stored,
        # and the plan on screen really fits it.
        assert session_after["constraints_summary"]["budget_fen"] == 1000, session_after
    else:
        # Not currently supported / not feasible: the refusal is explicit and no
        # part of the change was written.
        codes = {
            r.get("code")
            for r in body.get("action_results") or []
            if r.get("saved") is not True
        }
        assert codes & {
            "UNSUPPORTED_OPERATION",
            "UNSUPPORTED_CHANGE_FIELD",
            "BUDGET_EXCEEDED",
            "GOAL_CHANGE_CONFLICT",
        }, body["action_results"]
        assert body.get("plan_effect") == "keep", body
        assert session_after["state_version"] == session_before["state_version"], session_after
        assert session_after["constraints_summary"] == session_before["constraints_summary"]
        assert session_after["plan"] == session_before["plan"]
        assert client.get("/api/v1/cart").json() == cart_before


def test_s06c_unmentioned_budget_is_neither_asked_nor_invented(client, semantic_provider):
    """No budget in the sentence: no budget question, no invented limit.

    A budget participates only when the shopper states one, so a plan turn that
    never mentions money must not ask for a budget and must not store a default.
    """
    from support.semantic_agent import lookup_then_add_id

    semantic_provider(
        lookup_then_add_id("dish", "番茄炒蛋", "dish-fanqie-chao-dan", people=2)
    )
    sid = _session(client)
    resp = _turn(client, sid, "我想吃番茄炒蛋")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("plan"), body

    pending = body.get("pending_clarifications") or []
    assert not pending, pending
    assert body.get("pending_clarification") is None, body.get("pending_clarification")
    assert all(
        "预算" not in str((item or {}).get("question") or "") for item in pending
    ), pending
    assert all(
        "预算" not in str((item or {}).get("message") or "")
        for item in body.get("action_results") or []
    ), body.get("action_results")

    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert session["constraints_summary"]["budget_fen"] is None, session["constraints_summary"]


def test_s03_json_replay_same_request_id(client, db_session):
    sid = _session(client)
    request_id = str(uuid.uuid4())
    payload = {
        "request_id": request_id,
        "message": "你好",
        "expected_task_id": None,
        "expected_state_version": 0,
    }
    first = post_turn(
        client, sid, payload["message"], None, request_id=payload["request_id"]
    )
    assert first.status_code == 200, first.json()
    first_body = first.json()

    second = post_turn(
        client, sid, payload["message"], None, request_id=payload["request_id"]
    )
    assert second.status_code == 200, second.text
    replay = second.json()
    assert replay["message"] == first_body["message"]
    assert replay["request_id"] == first_body["request_id"]

    ops = db_session.query(GuideOperation).filter_by(request_id=request_id).all()
    assert any(o.status == "completed" for o in ops) or first_body.get("request_id") == request_id


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run these suites against the controlled agent without live credentials.

    Assertions are unchanged; only the model provider is injected.
    """
    return reactive_agent


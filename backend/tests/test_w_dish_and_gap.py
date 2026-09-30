"""P3 workflow probes: W03 W06 W09 W10 and M1b gap-fill via /turns."""

from __future__ import annotations

from uuid import uuid4

import pytest

from support import post_turn


def turn(client, sid, message, previous=None, *, expect_status=200):
    previous = previous or {}
    response = post_turn(client, sid, message, previous)
    assert response.status_code == expect_status, response.text
    return response.json() if response.status_code == 200 else response


def session(client):
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


def plan(client, message="我想吃番茄炒蛋"):
    sid = session(client)
    result = turn(client, sid, message)
    assert result.get("plan"), result
    return result


def confirm(client, body, key=None):
    items = body["plan"]["items"]
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": key or str(uuid4())},
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


def _plan_names(body):
    return " ".join(i.get("name") or "" for i in (body.get("plan") or {}).get("items", []))


def test_w03_gap_fill_clarify_append_or_new_plan(client):
    """W03: post-confirm people change clarifies append vs 另做一份; new plan is independent."""
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    first = plan(client)
    confirmed = confirm(client, first).json()
    assert confirmed["status"] == "completed", confirmed

    clarify = turn(client, first["session_id"], "改成四人份", confirmed)
    assert clarify["status"] == "clarifying", clarify
    assert clarify.get("plan_effect") == "keep"
    assert not clarify.get("plan")
    pending = clarify.get("pending_clarification") or {}
    assert pending.get("slot") == "gap_fill_scope"
    option_ids = {o["id"] for o in pending.get("options", [])}
    assert "append" in option_ids and "new_plan" in option_ids

    new_plan = turn(client, first["session_id"], "另做一份", clarify)
    assert new_plan["task_id"] != first["task_id"], new_plan
    assert new_plan.get("plan"), new_plan
    assert new_plan["status"] == "awaiting_confirmation", new_plan
    tomato_qty = sum(
        i["quantity"] for i in new_plan["plan"]["items"] if "tomato" in i["sku_id"]
    )
    assert tomato_qty == 2, {"tomato_qty": tomato_qty, "items": new_plan["plan"]["items"]}

    with SessionLocal() as db:
        old_task = db.get(GuideTask, first["task_id"])
        assert old_task.status == "completed"
        assert old_task.cart_result_json

    second_confirm = confirm(client, new_plan)
    assert second_confirm.status_code == 200, second_confirm.text


def test_w06_dish_negation_switches_to_new_dish(client):
    """W06: negating dish A and naming B must plan B, not keep A."""
    first = plan(client)
    assert "番茄" in _plan_names(first) or "tomato" in _plan_names(first).lower()

    switched = turn(client, first["session_id"], "不做番茄炒蛋了，改做宫保鸡丁", first)
    assert switched.get("plan"), switched
    names = _plan_names(switched)
    assert "花生" in names or "鸡胸" in names
    assert "番茄" not in names


def test_w09_xiaochaorou_not_qingjiao_rousi(client):
    """W09: 小炒肉 must not silently map to dish-qingjiao-rousi."""
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    first = plan(client)
    following = turn(client, first["session_id"], "换成小炒肉", first)
    with SessionLocal() as db:
        task = db.get(GuideTask, following["task_id"])
        assert task.active_template_id != "dish-qingjiao-rousi", {
            "active_template_id": task.active_template_id,
            "turn": following,
        }
    if following.get("plan"):
        assert "青椒肉丝" not in _plan_names(following)


def test_w09_typo_and_ambiguous_via_turns(client, semantic_provider):
    """W09: a typo resolves to the real dish once confirmed; an ambiguous name asks.

    The model names what it heard and the server binds only an exact hit. A
    typo is offered its real similar dishes instead of being guessed; picking
    one plans it. An ambiguous name against a live plan offers the rows its
    lookup really returned as one question, instead of guessing one of them.
    """
    from support.semantic_agent import add_named, lookup_then_add

    semantic_provider([*lookup_then_add("dish", "蕃茄炒蛋"), add_named("dish", "番茄炒蛋", people=2)])
    sid = session(client)

    typo = turn(client, sid, "我想吃蕃茄炒蛋")
    assert not typo.get("plan"), typo
    offered = [c.get("name") for c in (typo.get("pending_clarification") or {}).get("candidates") or []]
    assert "番茄炒蛋" in offered, offered

    picked = turn(client, sid, "对，番茄炒蛋", typo)
    assert picked.get("plan"), picked
    assert picked["status"] == "awaiting_confirmation", picked
    assert picked["plan"]["targets"][0]["target_id"] == "dish-fanqie-chao-dan", picked

    # "炒蛋" names no dish exactly; the offline (lexical) index answers the query
    # "蛋" with several egg dishes, which become the options of the one question.
    semantic_provider([*lookup_then_add("dish", "蛋", "炒蛋", relation="append")])
    ambiguous = turn(client, sid, "再来个炒蛋", picked)
    # The plan already on screen stays pending confirmation — the turn asks, it
    # does not replace what the shopper was looking at.
    assert ambiguous["status"] == "awaiting_confirmation", ambiguous
    assert ambiguous["plan_effect"] == "keep", ambiguous
    assert ambiguous.get("plan") is None, ambiguous
    assert ambiguous.get("pending_clarification")
    candidates = (ambiguous.get("pending_clarification") or {}).get("candidates") or []
    assert len(candidates) >= 2
    assert len(ambiguous["pending_clarifications"]) == 1, ambiguous["pending_clarifications"]


def test_w10_vague_meal_offers_dish_candidates(client, semantic_provider):
    """W10: 随便吃点 answers with dishes this store can build, not raw ingredients.

    The answer is drawn from the rows a real open recommendation returned, and
    naming one of those dishes retrieves and plans it.
    """
    from support.semantic_agent import lookup_then_add, recommend_then, topic_rows

    shown: list[str] = []

    def answer(request):
        rows = topic_rows(request)
        assert len(rows) >= 2, rows
        shown.extend(str(r.get("name") or "") for r in rows)
        return {"reply": "可以做这些：" + "、".join(shown)}

    semantic_provider(recommend_then(None, answer))
    sid = session(client)
    vague = turn(client, sid, "今晚随便吃点")
    # An answer before any purchase is not a task step.
    assert vague["status"] == "understanding", vague
    assert vague["plan_effect"] == "keep", vague
    assert not vague.get("plan")
    assert shown[0] and shown[0] in vague["message"], vague["message"]

    chosen = shown[0]
    semantic_provider(lookup_then_add("dish", chosen, people=2))
    picked = turn(client, sid, chosen, vague)
    assert picked.get("plan"), picked
    assert picked["status"] == "awaiting_confirmation", picked


def test_m1b_gap_fill_2_to_4_via_turns(client):
    """M1b: post-confirm 2→4 gap plan is produced via /turns (append must carry people)."""
    first = plan(client)
    tomato_sku = next(i["sku_id"] for i in first["plan"]["items"] if "tomato" in i["sku_id"])

    confirmed = confirm(client, first).json()
    assert confirmed["status"] == "completed"

    clarify4 = turn(client, first["session_id"], "改成四人份", confirmed)
    assert clarify4["status"] == "clarifying"

    gap4 = turn(client, first["session_id"], "追加四人份", clarify4)
    assert gap4.get("plan"), gap4
    assert gap4["task_id"] != first["task_id"]
    assert "差额" in (gap4.get("message") or "")
    gap4_qty = sum(
        i["quantity"] for i in gap4["plan"]["items"] if i["sku_id"] == tomato_sku
    )
    assert gap4_qty == 1, {"gap4_qty": gap4_qty, "items": gap4["plan"]["items"]}


def test_m1b_gap_fill_second_zero_delta_via_turns(client):
    """M1b: when chain already satisfies target people, append should zero_delta via /turns."""
    first = plan(client)
    confirmed = confirm(client, first).json()
    assert confirmed["status"] == "completed"

    clarify = turn(client, first["session_id"], "改成两人份", confirmed)
    assert clarify["status"] == "clarifying"

    try:
        response = post_turn(client, first['session_id'], "追加两人份", {"task_id": clarify["task_id"], "state_version": clarify["state_version"], "session_version": clarify["session_version"]}, request_id=str(uuid4()))
    except Exception as exc:
        pytest.fail(f"zero_delta /turns should return JSON 200, got API error: {exc}")
    assert response.status_code == 200, response.text
    zero = response.json()
    assert zero.get("plan_effect") == "keep"
    assert not zero.get("plan")
    msg = zero.get("message") or ""
    assert "无需追加" in msg or "无需" in msg, zero


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

"""Shopping-workflow acceptance tests (plan tasks 1–3).

These run the real semantic turn — the loop, the read port, the plan-change
executor, the business services and the database. Only the *model* is a test
double, so no credentials and no network are used.

They cover the behaviours the iteration was asked for:

* a verified positive target produces a committed plan before any answer text
* incremental targets preserve the user's selections and hand-edited quantities
* open scenarios are freely shoppable and are built generically from their own
  components/common_tags
* only an explicit confirmation (button or chat) mutates the cart, and a
  per-row add is never bought twice

Every turn is scripted in the one-pass **proposal** protocol
(``semantic_provider``): a write names its target and the lookup it needs in one
model call; only an answer drawn from real results takes a second
(``lookup_then``). The retired tool-call protocol is
gone, and with it every server-side reading of the sentence — so a test that
used to rely on the server refusing, resolving or replacing something now states
explicitly which proposal is being made. Assertions tied to the retired chain
are not treated as evidence of current real-model quality.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from support import create_session, post_turn
from support.semantic_agent import (
    lookup_then_add,
    lookup_then_add_id,
    pick,
    reply_only,
    request_amend,
    request_new,
)
from test_semantic_phase1_purchase import indexed_client

TOMATO = "dish-fanqie-chao-dan"
TOMATO_SOUP = "dish-fanqie-dan-tang"
QINGJIAO_ROUSI = "dish-qingjiao-rousi"
EGG_SKU = "demo:eggs-fresh-6pack"
COLA_SKU = "demo:cola-330ml"


def turn(
    client,
    session_id: str,
    message: str,
    previous: dict | None = None,
    *,
    request_id: str | None = None,
):
    return post_turn(
        client,
        session_id,
        message,
        previous,
        request_id=request_id,
    )


def stream_turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{session_id}/turns/stream",
        json={
            "request_id": str(uuid.uuid4()),
            "message": message,
            "expected_task_id": previous.get("task_id"),
            "expected_state_version": previous.get("state_version", 0),
            "expected_session_version": previous.get("session_version"),
        },
    ) as response:
        assert response.status_code == 200, response.read()
        return [
            json.loads(chunk.removeprefix("data: "))
            for chunk in "".join(response.iter_text()).split("\n\n")
            if chunk.startswith("data:")
        ]


def _db(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def _owner(client) -> str:
    db = _db(client)
    return str(db.execute(text("SELECT owner_id FROM guide_sessions LIMIT 1")).scalar())


def _snapshot(client, session_id: str) -> dict:
    return client.get(f"/api/v1/guide/sessions/{session_id}").json()


def confirm(client, body, key: str | None = None, items=None):
    payload = items if items is not None else [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in body["plan"]["items"]
        if i.get("selected", True)
    ]
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
        json={
            "plan_id": body["plan"]["plan_id"],
            "plan_version": body["plan"]["plan_version"],
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
            "selected_items": payload,
        },
    )


def add_row(client, body, sku_id: str, quantity: int = 1, key: str | None = None):
    return client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/items/{sku_id}/add",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": quantity,
            "expected_state_version": body["state_version"],
            "expected_session_version": body["session_version"],
        },
    )


def plan_for(client, semantic_provider, *, message="我想吃番茄炒蛋，2人", name="番茄炒蛋", dish=TOMATO):
    """A real retrieve → add turn producing a real plan.

    One model call names the dish and looks it up; the server binds the exact
    hit, so the plan on screen is the dish this test names, built by the real
    services.
    """
    semantic_provider([*lookup_then_add_id("dish", name, dish, people=2)])
    sid = create_session(client)
    return turn(client, sid, message).json()


def add_scenario(*, people: int = 4):
    """Add the open hotpot scenario generically."""

    def build(request):
        scenario = request["candidates"]["scenarios"][0]
        return pick("scenario", scenario, request=request, people=people)

    return build


# ---------------------------------------------------------------- card first


def test_verified_dish_is_committed_before_any_answer_text(client, semantic_provider):
    """The model only promises; the server still lands a panel — and lands it first."""
    semantic_provider(
        [
            {
                "reply": "已准备好清单。",
                **request_new("dish", "番茄炒蛋", people=2),
                "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
            }
        ]
    )
    sid = create_session(client)
    events = stream_turn(client, sid, "我想吃番茄炒蛋，2人")

    types = [event["type"] for event in events]
    assert "plan.ready" in types, events
    deltas = [
        index
        for index, event in enumerate(events)
        if event["type"] == "answer.delta" and (event.get("payload") or {}).get("delta")
    ]
    assert deltas, "the answer text should still stream"
    assert types.index("plan.ready") < min(deltas), "answer text preceded the product panel"

    completed = [event for event in events if event["type"] == "turn.completed"][-1]
    plan = completed["payload"]["plan"]
    assert plan["items"]
    assert plan["targets"][0]["target_id"] == TOMATO
    # The authoritative message is the server's: no invented price, no promise.
    assert "已准备好清单" not in completed["payload"]["message"]
    assert "¥" in completed["payload"]["message"]
    assert client.get("/api/v1/cart").json()["items"] == []


def test_undeclared_headcount_builds_plan_without_user_attribution(
    client, semantic_provider
):
    """Recipe basis may drive quantities, but it is never reported as user input."""
    semantic_provider([*lookup_then_add_id("dish", "番茄炒蛋", TOMATO)])
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋").json()

    assert body["plan"], body
    assert body["plan_effect"] == "replace", body
    assert "people" not in (body.get("missing_slots") or []), body
    assert "几个人吃" not in body["message"], body["message"]
    assert "默认" not in body["message"], body["message"]
    assert "按你说的" not in body["message"], body["message"]
    assert body["plan"]["targets"][0]["people_source"] == "default", body["plan"]["targets"]
    session = _snapshot(client, sid)
    assert session["constraints_summary"].get("people") is None, session["constraints_summary"]


def test_missing_headcount_builds_first_then_amend_applies_user_count(
    client, semantic_provider
):
    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO),
            {"reply": "按两个人份调整。", **request_amend(changes={"set": {"people": 2}})},
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋").json()
    assert first["plan"], first
    assert first["plan"]["targets"][0]["people_source"] == "default", first["plan"]["targets"]

    built = turn(client, sid, "两个人", first).json()
    assert built["plan"], built
    assert built["plan"]["targets"][0]["people"] == 2, built["plan"]["targets"]
    assert built["plan"]["targets"][0]["people_source"] == "user", built["plan"]["targets"]


def test_a_model_question_holds_the_dish_until_answered(client, semantic_provider):
    """A question the model still has outranks the write it proposed.

    A headcount question has no candidate options: the model asks it in words,
    the server persists it, and nothing is built until it is answered.
    """
    semantic_provider(
        [
            {
                **request_new("dish", "番茄炒蛋"),
                "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
                "questions": [
                    {"slot": "people", "question": "你们几个人吃？", "options": []}
                ],
            }
        ]
    )
    sid = create_session(client)
    body = turn(client, sid, "我想吃番茄炒蛋").json()

    assert body["plan"] is None, body
    assert [p["question"] for p in body["pending_clarifications"]] == [
        "你们几个人吃？"
    ]
    assert client.get("/api/v1/cart").json()["items"] == []


# ------------------------------------------------- negatives and information


@pytest.mark.parametrize(
    "message",
    [
        "不要番茄炒蛋",
        "不想吃番茄炒蛋",
        "番茄炒蛋怎么做",
        "番茄炒蛋和番茄蛋汤有什么区别",
        "番茄炒蛋还是青椒肉丝",
        "第二道不要",
    ],
)
def test_negative_and_informational_turns_never_create_a_plan(
    client, semantic_provider, message
):
    """No mutation, no plan, no cart.

    The retired chain refused these sentences server-side with a negative-phrase
    regex over the raw text. That guard does not exist any more, so what is
    scripted here is a model that proposes nothing: the server contract under
    test is "a turn with no mutation writes nothing", **not** "a real model would
    decline" — that is a model-quality claim and needs real-model acceptance.
    """
    semantic_provider([reply_only("可以继续说想换成什么。")])
    sid = create_session(client)
    body = turn(client, sid, message).json()
    assert body["plan"] is None, body
    assert body["task_id"] is None, body
    assert body["plan_effect"] == "keep"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_negated_dish_is_refused_by_the_model_not_by_a_server_guard(
    client, semantic_provider
):
    """The retired ToolGate refused a rejected target; nothing refuses it now.

    This pins the *mechanism*, not a wish: whether 「不要番茄炒蛋」 becomes an order
    is decided entirely by whether the model proposes the add. There is no
    server-side reading of the sentence left to report a code, and no runtime
    support for one is simulated here. This gap can only be closed by
    real-model acceptance.
    """
    # A model that (wrongly) proposes the purchase names the bare dish.
    semantic_provider([*lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2)])
    sid = create_session(client)
    body = turn(client, sid, "不要番茄炒蛋，2人").json()

    assert body["plan"], body
    codes = {r.get("code") for r in body["action_results"]}
    assert not codes & {"TARGET_REJECTED_BY_USER", "INFORMATIONAL_TURN"}, codes
    assert client.get("/api/v1/cart").json()["items"] == []


def test_typo_asks_with_real_candidates_instead_of_ordering(client, semantic_provider):
    """A misspelled dish name is a question, not a wrongful order.

    The acceptance matrix puts "菜名错别字" under "不误建单": offer the real
    similar dishes and let the user confirm — never claim the dish does not
    exist and never order on their behalf. The model names what it heard; the
    server binds only an exact hit and asks about the similar ones.
    """
    semantic_provider([*lookup_then_add("dish", "蕃茄炒蛋")])
    sid = create_session(client)
    body = turn(client, sid, "我想吃蕃茄炒蛋").json()

    assert body["plan"] is None, body
    assert body["task_id"] is None, body
    pending = body["pending_clarifications"][0]
    names = [c.get("name") for c in pending.get("candidates") or []]
    assert "番茄炒蛋" in names, names
    assert "暂未收录" not in body["message"]
    assert pending["question"] in body["message"]


def test_plan_ready_always_carries_the_merged_persisted_plan(client, semantic_provider):
    """The event must publish what is stored, not the single tool result.

    Emitting the freshly built target alone would make the client drop the rows of
    every other target until the turn finished.
    """
    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            *lookup_then_add_id("dish", "番茄蛋汤", TOMATO_SOUP, relation="append"),
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    events = stream_turn(client, sid, "还想吃番茄蛋汤", first)
    ready = [event for event in events if event["type"] == "plan.ready"][-1]["payload"]["plan"]
    terminal = [event for event in events if event["type"] == "turn.completed"][-1]["payload"]
    authoritative = terminal["plan"]

    assert ready["plan_id"] == authoritative["plan_id"]
    assert ready["plan_version"] == authoritative["plan_version"]
    assert {i["sku_id"] for i in ready["items"]} == {i["sku_id"] for i in authoritative["items"]}
    assert len(ready["targets"]) == 2, ready["targets"]
    assert any("tomato" in i["sku_id"] for i in ready["items"]), "the first dish's rows were lost"

    stored = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert stored["plan_version"] == ready["plan_version"]


def test_partial_shorthand_resolves_against_the_shown_candidates(client, semantic_provider):
    """The shorthand is resolved by the model, against the candidates it was shown.

    The retired chain resolved 「炒肉丝」 server-side with a longest-common-substring
    pass. That module is gone; what replaces it is the session-owned pending
    question: the dishes the shopper was really shown travel into the next turn,
    and the model picks one of *those* refs.
    """

    def pick_the_shown_dish(request):
        for row in request["candidates"]["dishes"]:
            if "青椒肉丝" in str(row.get("name") or ""):
                return pick("dish", row, request=request)
        raise AssertionError(
            f"候选里没有被展示过的青椒肉丝：{request['candidates']['dishes']}"
        )

    provider = semantic_provider([*lookup_then_add("dish", "青椒炒肉"), pick_the_shown_dish])
    sid = create_session(client)
    first = turn(client, sid, "我想做个青椒炒肉").json()
    assert first["plan"] is None, first
    names = [c["name"] for c in first["pending_clarifications"][0]["candidates"]]
    assert "青椒肉丝" in names, names

    # The shopper does not repeat the canonical name — only part of it.
    second = turn(client, sid, "试试炒肉丝吧，2人", first).json()
    assert second["plan"], second
    assert second["plan"]["targets"][0]["target_id"] == QINGJIAO_ROUSI
    assert provider.requests[-1]["pending_clarifications"], (
        "the candidates the shopper was shown must reach the model again"
    )


# ------------------------------------------------------- incremental targets


def test_append_keeps_selection_and_hand_edited_quantity(indexed_client, semantic_provider):
    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            *lookup_then_add_id("dish", "番茄蛋汤", TOMATO_SOUP, relation="append"),
        ]
    )
    client = indexed_client
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    tomato = next(i for i in first["plan"]["items"] if "tomato" in i["sku_id"])

    # The shopper edits a quantity and (de)selects a row on the server.
    revision = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": first["session_version"],
            "expected_state_version": first["state_version"],
            "base_plan_id": first["plan"]["plan_id"],
            "base_plan_version": first["plan"]["plan_version"],
            "client_edit_sequence": 1,
            "items": [
                {
                    "sku_id": i["sku_id"],
                    "quantity": tomato["quantity"] + 2 if i["sku_id"] == tomato["sku_id"] else i["quantity"],
                    "selected": i.get("selected", True),
                }
                for i in first["plan"]["items"]
            ],
        },
    )
    assert revision.status_code == 200, revision.text
    revised = revision.json()
    edited_quantity = next(
        i["quantity"] for i in revised["items"] if i["sku_id"] == tomato["sku_id"]
    )
    assert edited_quantity == tomato["quantity"] + 2

    current = {
        "task_id": first["task_id"],
        "state_version": revised["state_version"],
        "session_version": revised["session_version"],
    }
    second = turn(client, sid, "还想吃番茄蛋汤", current).json()
    assert second["plan"], second
    targets = {t["target_id"] for t in second["plan"]["targets"]}
    assert targets == {TOMATO, TOMATO_SOUP}, targets
    kept = next(
        i for i in second["plan"]["items"] if i["sku_id"] == tomato["sku_id"]
    )
    assert kept["quantity"] >= edited_quantity, "the hand-edited quantity survived the append"
    assert kept["quantity_source"] == "user"


def test_explicit_add_dish_keeps_shared_egg_contribution_and_old_selection(
    indexed_client, semantic_provider
):
    semantic_provider(
        [
            *lookup_then_add_id(
                "dish", "番茄炒蛋", TOMATO, mode="self_cook",
                constraints={"budget_yuan": 100},
            ),
            *lookup_then_add_id(
                "dish", "蛋炒饭", "dish-dan-chao-fan", relation="append",
                mode="self_cook",
            ),
        ]
    )
    client = indexed_client
    sid = create_session(client)
    first = turn(client, sid, "今晚自己做番茄炒蛋，预算100元，没有忌口").json()
    original_selection = {
        item["sku_id"]: item["selected"] for item in first["plan"]["items"]
    }

    appended = turn(client, sid, "再加一道蛋炒饭，自己做", first).json()

    assert appended["plan_effect"] == "replace", appended
    assert appended["pending_clarifications"] == [], appended
    assert {target["target_id"] for target in appended["plan"]["targets"]} == {
        TOMATO,
        "dish-dan-chao-fan",
    }
    assert all(
        target["fulfillment_mode"] == "self_cook"
        for target in appended["plan"]["targets"]
    )
    by_sku = {item["sku_id"]: item for item in appended["plan"]["items"]}
    assert {
        sku_id: by_sku[sku_id]["selected"] for sku_id in original_selection
    } == original_selection

    shared_egg = by_sku[EGG_SKU]
    assert shared_egg["selected"] is True
    assert {row["group_id"] for row in shared_egg["contributions"]} == {
        f"dish:{TOMATO}",
        "dish:dish-dan-chao-fan",
    }


def test_named_dish_without_add_or_replace_still_asks(indexed_client, semantic_provider):
    def append_after_answer(request):
        return lookup_then_add_id(
            "dish", "蛋炒饭", "dish-dan-chao-fan",
            relation="append", mode="self_cook",
        )[0](request)

    provider = semantic_provider(
        [
            *lookup_then_add_id(
                "dish", "番茄炒蛋", TOMATO, mode="self_cook",
                constraints={"budget_yuan": 100},
            ),
            *lookup_then_add_id(
                "dish", "蛋炒饭", "dish-dan-chao-fan", mode="self_cook"
            ),
            append_after_answer,
        ]
    )
    client = indexed_client
    sid = create_session(client)
    first = turn(client, sid, "今晚自己做番茄炒蛋，预算100元，没有忌口").json()
    before = _snapshot(client, sid)["plan"]

    ambiguous = turn(client, sid, "我想吃蛋炒饭，自己做", first).json()

    assert ambiguous["route"] == "clarify", ambiguous
    assert ambiguous["pending_clarifications"][0]["slot"] == "goal_relation", ambiguous
    assert ambiguous["plan_effect"] == "keep", ambiguous
    assert ambiguous["plan"] is None, ambiguous
    pending = ambiguous["pending_clarifications"][0]
    after = _snapshot(client, sid)["plan"]
    assert after["plan_id"] == before["plan_id"]
    assert after["plan_version"] == before["plan_version"]
    assert {target["target_id"] for target in after["targets"]} == {TOMATO}
    assert client.get("/api/v1/cart").json()["items"] == []

    appended = turn(
        client, sid, "追加，保留原来的番茄炒蛋", ambiguous
    ).json()
    answer_request = provider.requests[-1]
    assert any(
        question["question_id"] == pending["question_id"]
        for question in answer_request["pending_clarifications"]
    )

    assert appended["pending_clarifications"] == [], appended
    assert {target["target_id"] for target in appended["plan"]["targets"]} == {
        TOMATO,
        "dish-dan-chao-fan",
    }
    persisted = _snapshot(client, sid)
    assert persisted["pending_clarifications"] == []
    assert persisted["constraints_summary"]["budget_fen"] == 10000
    assert {target["target_id"] for target in persisted["plan"]["targets"]} == {
        TOMATO,
        "dish-dan-chao-fan",
    }
    assert client.get("/api/v1/cart").json()["items"] == []


def test_direct_product_append_keeps_the_dish_and_counts_in_pieces(client, semantic_provider):
    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            *lookup_then_add_id("product", "可乐 330毫升", COLA_SKU, relation="append"),
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    # A direct product request: the model names the bottle, the server counts it.
    second = turn(client, sid, "还要一瓶可乐", first).json()
    assert second["plan"], second
    kinds = {t["kind"] for t in second["plan"]["targets"]}
    assert kinds == {"dish", "product"}, kinds
    cola = next(i for i in second["plan"]["items"] if "cola" in i["sku_id"])
    assert cola["quantity"] == 1, "a drink is counted in bottles, not by headcount"
    assert any("tomato" in i["sku_id"] for i in second["plan"]["items"])


def test_redoing_a_target_is_refused_and_a_new_dish_appends(client, semantic_provider):
    """「不做番茄炒蛋了，改做番茄蛋汤」 proposed as a replace *plus* a row remove.

    A replace must not also edit the plan it replaces, so the compound proposal
    is refused outright instead of being half-executed: the plan on screen stays
    exactly what it was. Adding the dish on its own then appends to what is
    still there.
    """

    def redo_the_target(request):
        groups = (request.get("current_plan") or {}).get("groups") or []
        assert groups, request.get("current_plan")
        return {
            **request_new("dish", "番茄蛋汤", relation="switch"),
            "lookups": [{"kind": "dish", "query": "番茄蛋汤"}],
            "focus": {"ref": groups[0]["ref"], "name": groups[0]["name"]},
            "edit": {"op": "remove"},
        }

    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            redo_the_target,
            *lookup_then_add_id("dish", "番茄蛋汤", TOMATO_SOUP, relation="append"),
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    refused = turn(client, sid, "不做番茄炒蛋了，改做番茄蛋汤", first).json()
    assert refused["plan_effect"] == "keep", refused
    # The compound batch is really refused: no partial write, no success claim.
    # The safety-equivalent refusal may be the executor's UNSUPPORTED_OPERATION or
    # the gate's own refusal (WRITE_BLOCKED / GOAL_CHANGE_CONFLICT); every one of
    # them means "nothing was written".
    refused_codes = {r.get("code") for r in refused["action_results"]}
    assert refused_codes & {
        "UNSUPPORTED_OPERATION",
        "WRITE_BLOCKED",
        "GOAL_CHANGE_CONFLICT",
    }, refused["action_results"]
    assert not any(r.get("status") == "committed" for r in refused["action_results"]), refused["action_results"]
    assert client.get("/api/v1/cart").json()["items"] == []
    kept = _snapshot(client, sid)["plan"]
    assert kept["plan_version"] == first["plan"]["plan_version"]
    assert {t["name"] for t in kept["targets"]} == {"番茄炒蛋"}

    # The dish can still be added, and what is on screen is kept, not replaced.
    # The refused turn persisted its clarification, so the retry anchors on it.
    appended = turn(client, sid, "那就来一份番茄蛋汤", refused).json()
    assert appended["plan"], appended
    names = {t["name"] for t in appended["plan"]["targets"]}
    assert names == {"番茄炒蛋", "番茄蛋汤"}, names
    assert any("tomato" in i["sku_id"] for i in appended["plan"]["items"])


def test_headcount_change_rescales_only_the_recipe(client, semantic_provider):
    def resize_the_dish(request):
        group = next(
            g
            for g in (request.get("current_plan") or {}).get("groups") or []
            if g["group_id"] == f"dish:{TOMATO}"
        )
        return {
            "reply": "好，按新人数重新配。",
            **request_amend(
                focus=group["ref"], name=group["name"], changes={"set": {"people": 4}}
            ),
        }

    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            *lookup_then_add_id("product", "可乐 330毫升", COLA_SKU, relation="append"),
            resize_the_dish,
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    with_cola = turn(client, sid, "还要一瓶可乐", first).json()
    cola_before = next(
        i["quantity"] for i in with_cola["plan"]["items"] if "cola" in i["sku_id"]
    )
    tomato_before = next(
        i["quantity"] for i in with_cola["plan"]["items"] if "tomato" in i["sku_id"]
    )

    resized = turn(client, sid, "改成四个人", with_cola).json()
    assert resized["plan"], resized
    cola_after = next(
        i["quantity"] for i in resized["plan"]["items"] if "cola" in i["sku_id"]
    )
    tomato_after = next(
        i["quantity"] for i in resized["plan"]["items"] if "tomato" in i["sku_id"]
    )
    assert cola_after == cola_before, "a drink must not be multiplied by the headcount"
    assert tomato_after > tomato_before, "the recipe's quantities must follow the headcount"
    target = next(t for t in resized["plan"]["targets"] if t["kind"] == "dish")
    assert target["people"] == 4 and target["people_source"] == "user"


def test_second_dish_without_stock_requires_choice_then_appends_partial_group(
    indexed_client, semantic_provider
):
    """A core gap previews first, then keeps both groups after explicit opt-in."""
    second_target = lookup_then_add_id(
        "dish", "番茄蛋汤", TOMATO_SOUP, relation="append"
    )[0]

    def opt_in(request):
        question = next(
            item for item in request["pending_clarifications"]
            if item["slot"] == "supply_gap_choice"
        )
        return {
            **second_target(request),
            "resolved_questions": [question["question_id"]],
        }

    semantic_provider([
        *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
        second_target,
        opt_in,
    ])
    client = indexed_client
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()
    db = _db(client)
    original_plan_json = db.execute(
        text("SELECT plan_json FROM guide_tasks WHERE task_id = :task_id"),
        {"task_id": first["task_id"]},
    ).scalar_one()
    # Zero *every* egg SKU: zeroing one pack size is no longer a shortage, because
    # the picker now prefers a sellable SKU that really has stock.
    db.execute(text("UPDATE offers SET available_qty = 0 WHERE sku_id LIKE 'demo:eggs%'"))
    db.commit()

    preview = turn(client, sid, "还想吃番茄蛋汤", first).json()
    assert preview["plan_effect"] == "keep", preview
    assert preview["plan"] is None, preview
    assert preview["pending_clarifications"][0]["slot"] == "supply_gap_choice", preview
    assert "鸡蛋" in preview["pending_clarifications"][0]["question"], preview
    assert client.get("/api/v1/cart").json()["items"] == []
    assert db.execute(
        text("SELECT plan_json FROM guide_tasks WHERE task_id = :task_id"),
        {"task_id": first["task_id"]},
    ).scalar_one() == original_plan_json

    second = turn(client, sid, "那就先买能买到的", preview).json()
    assert second["plan_effect"] == "replace", second
    plan = second["plan"]
    # The first dish's rows are still there, and the second target is recorded.
    assert any("tomato" in i["sku_id"] for i in plan["items"])
    assert {t["target_id"] for t in plan["targets"]} == {TOMATO, TOMATO_SOUP}
    # The zero-stock egg is a non-selectable row plus a structured gap: it can
    # never be bought, while the first dish's tomato row stays intact and buyable.
    egg_rows = [i for i in plan["items"] if i["sku_id"] == EGG_SKU]
    assert egg_rows, plan["items"]
    assert all(
        i["availability"] == "out_of_stock" and i["max_addable_quantity"] == 0
        for i in egg_rows
    ), egg_rows
    tomato_rows = [i for i in plan["items"] if "tomato" in i["sku_id"]]
    assert tomato_rows and all(
        i["selected"] and i["availability"] == "available" for i in tomato_rows
    ), tomato_rows
    egg_gaps = [g for g in plan["gaps"] if g["sku_id"] == EGG_SKU]
    assert egg_gaps and all(g["kind"] == "out_of_stock" for g in egg_gaps), plan["gaps"]
    assert all(g["available_quantity"] == 0 for g in egg_gaps), plan["gaps"]
    assert plan["coverage_mode"] == "partial", plan
    assert plan["can_confirm"] is True, plan
    assert "库存" in second["message"], second["message"]

    reloaded = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert any("tomato" in i["sku_id"] for i in reloaded["plan"]["items"])
    assert reloaded["plan"]["coverage_mode"] == "partial", reloaded["plan"]
    assert any(g["sku_id"] == EGG_SKU for g in reloaded["plan"]["gaps"]), reloaded["plan"]
    assert client.get("/api/v1/cart").json()["items"] == []


# ------------------------------------------------------------- open scenario


def test_scenario_builds_a_basket_without_a_pending_question(client, semantic_provider):
    semantic_provider([add_scenario()])
    sid = create_session(client)
    first = turn(client, sid, "想吃火锅，4人").json()
    # A generic scenario is built directly, without a hidden preference.
    assert first["pending_clarifications"] == []
    assert first["plan"], first
    assert len(first["plan"]["items"]) >= 3
    assert first["plan"]["targets"][0]["kind"] == "scenario"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_the_four_named_hotpots_are_independent_dishes(client, db_session):
    """Each named hotpot resolves as its own dish and builds a dish plan."""
    from app.agent.protocol import CandidateSet, Lookup, SemanticProposal
    from app.agent.tools.prepare_purchase_plan import guarded_prepare_purchase_plan
    from app.agent.tools.read import ReadTools

    expected = {
        "川渝火锅": "dish-chuanyu-huoguo",
        "潮汕牛肉火锅": "dish-chaoshan-niurou-huoguo",
        "清汤火锅": "dish-qingtang-huoguo",
        "贵州酸汤火锅": "dish-guizhou-suansoup-huoguo",
    }
    reads = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default")
    for name, dish_id in expected.items():
        candidates = CandidateSet()
        result = reads.serve(
            SemanticProposal(lookups=[Lookup("dish", name)]),
            candidates,
            lookup_limit=4,
        )[0]
        match = next(
            (m for m in result.get("matches") or [] if m["target_id"] == dish_id), None
        )
        assert match is not None, (name, result)
        candidate = candidates.resolve(match["ref"])
        assert candidate.kind == "dish", (name, candidate)
        plan = guarded_prepare_purchase_plan(
            db_session,
            store_id="store-demo-01",
            delivery_zone_id="zone-default",
            target_kind="dish",
            target_id=candidate.target_id,
            people=4,
        )
        assert plan.get("status") == "ok", (name, plan)
        assert plan["target_kind"] == "dish"
        assert plan["target"]["name"] == name


def test_generic_scenario_recalls_the_common_hotpot_products(client, db_session):
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    plan = service.build_scenario_plan("hotpot", people=4)
    assert plan["status"] == "ok", plan
    skus = {item["sku_id"] for item in plan["items"]}
    assert "demo:hotpot-base-200g" in skus
    assert skus, "the generic basket must recall real common hotpot products"


def test_hotpot_product_keeps_its_category_and_common_tags(client, db_session):
    from app.services.catalog_service import CatalogService

    product = CatalogService(db_session, "store-demo-01").get_product("demo:beef-neck-300g")
    assert product is not None
    assert product["category_id"] == "meat", "the meat category must not be lost"
    tags = set(product["usage_tags"])
    assert {"火锅", "火锅肥牛"} <= tags


def test_scenario_is_open_shopping_and_missing_components_are_suggestions(
    client, db_session
):
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    plan = service.build_scenario_plan("hotpot", people=4)
    base = next(i for i in plan["items"] if i["role"] == "optional")
    assert base, "scenario rows must be freely deselectable"
    # Deselecting everything optional must not mark the plan uncovered.
    merged = service.merge_plan(
        None,
        {
            **plan,
            "items": [{**i, "selected": False} for i in plan["items"]],
        },
        group_id=plan["group_id"],
        operation="replace",
    )
    assert merged["coverage_mode"] == "full"
    assert merged["can_confirm"] is False


# ------------------------------------------------------------- merge stability


def test_three_targets_and_a_per_row_add_survive_a_merge(client, db_session):
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)

    def target(group, quantity, *, added=0):
        return {
            "plan_id": "plan-merge",
            "plan_version": 1,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "target": {"group_id": group, "kind": "dish", "target_id": group, "name": group},
            "items": [
                {
                    "sku_id": EGG_SKU,
                    "quantity": quantity,
                    "recommended_quantity": quantity,
                    "quantity_source": "recommended",
                    "selected": True,
                    "role": "required",
                    "group_id": group,
                    "added_quantity": added,
                }
            ],
        }

    plan = service.merge_plan(None, target("dish:a", 1), group_id="dish:a", operation="append")
    plan = service.merge_plan(plan, target("dish:b", 2), group_id="dish:b", operation="append")
    plan = service.merge_plan(plan, target("dish:c", 4), group_id="dish:c", operation="append")
    assert plan["items"][0]["quantity"] == 7
    assert len(plan["items"][0]["contributions"]) == 3

    # Re-appending B must not add it a second time.
    plan = service.merge_plan(plan, target("dish:b", 2), group_id="dish:b", operation="append")
    assert plan["items"][0]["quantity"] == 7
    # A per-row add is remembered, and survives the next merge.
    plan = service.merge_plan(
        plan, target("dish:d", 1, added=1), group_id="dish:d", operation="append"
    )
    assert plan["items"][0]["added_quantity"] == 1
    assert plan["items"][0]["remaining_quantity"] == plan["items"][0]["quantity"] - 1


# ------------------------------------------------------------------ cart rules


def test_edits_never_touch_the_cart_and_confirm_writes_once(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    assert client.get("/api/v1/cart").json()["items"] == []

    key = str(uuid.uuid4())
    first = confirm(client, body, key)
    assert first.status_code == 200, first.text
    assert first.json()["items_added"], first.json()
    cart_after = client.get("/api/v1/cart").json()

    replay = confirm(client, body, key)
    assert replay.status_code in (200, 409), replay.text
    if replay.status_code == 200:
        assert client.get("/api/v1/cart").json()["items"] == cart_after["items"]


def test_per_row_add_is_not_bought_again_by_the_batch_confirm(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])

    added = add_row(client, body, tomato["sku_id"], tomato["quantity"])
    assert added.status_code == 200, added.text
    payload = added.json()
    assert payload["items_added"] == [
        {"sku_id": tomato["sku_id"], "quantity": tomato["quantity"]}
    ]
    cart = client.get("/api/v1/cart").json()
    assert sum(i["quantity"] for i in cart["items"] if i["sku_id"] == tomato["sku_id"]) == (
        tomato["quantity"]
    )

    row = next(i for i in payload["items"] if i["sku_id"] == tomato["sku_id"])
    assert row["added_quantity"] == tomato["quantity"]
    assert row["remaining_quantity"] == 0

    current = {
        "task_id": body["task_id"],
        "state_version": payload["state_version"],
        "session_version": payload["session_version"],
    }
    remaining = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in payload["items"]
        if i.get("selected", True) and i.get("remaining_quantity", i["quantity"]) > 0
    ]
    assert remaining, "the un-added rows are still outstanding"
    result = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": payload["plan_id"],
            "plan_version": payload["plan_version"],
            "expected_state_version": current["state_version"],
            "expected_session_version": current["session_version"],
            "selected_items": remaining,
        },
    )
    assert result.status_code == 200, result.text
    final = client.get("/api/v1/cart").json()
    tomato_total = sum(i["quantity"] for i in final["items"] if i["sku_id"] == tomato["sku_id"])
    assert tomato_total == tomato["quantity"], "the same row was bought twice"


def test_row_add_is_idempotent_per_request_id(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    key = str(uuid.uuid4())

    first = add_row(client, body, tomato["sku_id"], 1, key)
    assert first.status_code == 200, first.text
    cart_once = client.get("/api/v1/cart").json()

    replay = add_row(client, body, tomato["sku_id"], 1, key)
    assert replay.status_code in (200, 409), replay.text
    assert client.get("/api/v1/cart").json()["items"] == cart_once["items"]


# --------------------------------------------------------------- ownership


def test_cart_headroom_is_scoped_to_the_owning_shopper(client, semantic_provider):
    """Another owner's cart must not reduce this shopper's stock headroom."""
    from app.core.identity import COOKIE_NAME
    from app.models.cart import Cart, CartItem

    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])

    db = _db(client)
    other = Cart(owner_id="owner-elsewhere", store_id="store-demo-01", version=1)
    db.add(other)
    db.flush()
    db.add(
        CartItem(
            cart_id=other.id,
            sku_id=tomato["sku_id"],
            quantity=99,
            unit_price_fen=tomato["unit_price_fen"],
        )
    )
    db.commit()

    # The other owner's 99 packs must not show up as this shopper's headroom loss.
    assert body["plan"]["items"]
    row = next(i for i in body["plan"]["items"] if i["sku_id"] == tomato["sku_id"])
    assert row["max_addable_quantity"] >= 1, row
    added = add_row(client, body, tomato["sku_id"], 1)
    assert added.status_code == 200, added.text
    assert COOKIE_NAME == "sg_owner_id"


def test_a_second_owner_cannot_add_from_this_task(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])

    other = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
        headers={"Cookie": "sg_owner_id=someone-else"},
    )
    assert other.status_code == 200
    response = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/items/{tomato['sku_id']}/add",
        headers={"Idempotency-Key": str(uuid.uuid4()), "Cookie": "sg_owner_id=someone-else"},
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": 1,
            "expected_state_version": body["state_version"],
        },
    )
    assert response.status_code == 403, response.text


# --------------------------------------------------------- completed history


def test_completed_task_history_is_never_rewritten(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    confirmed = confirm(client, body)
    assert confirmed.status_code == 200, confirmed.text

    db = _db(client)
    before = db.execute(
        text(
            "SELECT requirements_json, plan_json, cart_result_json, state_version "
            "FROM guide_tasks WHERE task_id = :t"
        ),
        {"t": body["task_id"]},
    ).fetchone()

    # A stated headcount is the strongest attempt to rewrite a settled task: it
    # would rescale what was already bought. The mutation is refused and the
    # receipt says so.
    def resize_the_completed_dish(request):
        group = next(
            g
            for g in (request.get("current_plan") or {}).get("groups") or []
            if g["group_id"] == f"dish:{TOMATO}"
        )
        return {
            "reply": "好，按新人数重新配。",
            **request_amend(
                focus=group["ref"], name=group["name"], changes={"set": {"people": 4}}
            ),
        }

    semantic_provider([resize_the_completed_dish])
    response = turn(
        client,
        body["session_id"],
        "改成四个人",
        {
            "task_id": body["task_id"],
            "state_version": confirmed.json()["state_version"],
            "session_version": confirmed.json()["session_version"],
        },
    )
    assert response.status_code == 200, response.text
    settled = response.json()
    assert settled["plan_effect"] == "keep", settled
    assert any(
        r.get("code") == "TASK_COMPLETED_READ_ONLY" for r in settled["action_results"]
    ), settled["action_results"]

    db.expire_all()
    after = db.execute(
        text(
            "SELECT requirements_json, plan_json, cart_result_json, state_version "
            "FROM guide_tasks WHERE task_id = :t"
        ),
        {"t": body["task_id"]},
    ).fetchone()
    assert after[0] == before[0], "a completed task's requirements were mutated"
    assert after[1] == before[1]
    assert after[2] == before[2]


def test_adding_after_purchase_never_rebuys_the_purchased_items(
    client, semantic_provider
):
    body = plan_for(client, semantic_provider)
    confirmed = confirm(client, body)
    assert confirmed.status_code == 200
    bought = client.get("/api/v1/cart").json()

    # The completed task is still the session's current task, so the follow-up
    # turn addresses it with the versions the confirmation reported.
    semantic_provider([*lookup_then_add_id("product", "可乐 330毫升", COLA_SKU)])
    response = turn(
        client,
        body["session_id"],
        "还要一瓶可乐",
        {
            "task_id": body["task_id"],
            "state_version": confirmed.json()["state_version"],
            "session_version": confirmed.json()["session_version"],
        },
    )
    assert response.status_code == 200, response.text
    follow_up = response.json()
    assert follow_up["plan"], follow_up
    assert follow_up["task_id"] != body["task_id"], "a new task holds the new purchase"
    assert not any(
        "tomato" in i["sku_id"] for i in follow_up["plan"]["items"]
    ), "already-bought items must not come back for a second purchase"
    assert client.get("/api/v1/cart").json()["items"] == bought["items"]
    assert _owner(client)


# ------------------------------------------------------------------- money


def test_model_visible_facts_are_in_yuan_only(client, db_session):
    from app.llm.openai_transport import project_money_for_model

    projected = project_money_for_model(
        {
            "items": [
                {
                    "sku_id": "demo:x",
                    "unit_price_fen": 1280,
                    "line_total_fen": 2560,
                    "name": "一件商品",
                }
            ],
            "total_price_fen": 2560,
            "budget_fen": 5000,
            "note": "这件商品很划算，分两次就能买完。",
        }
    )
    assert projected["items"][0]["unit_price_yuan"] == 12.8
    assert projected["items"][0]["line_total_yuan"] == 25.6
    assert projected["total_price_yuan"] == 25.6
    assert projected["budget_yuan"] == 50.0
    assert "fen" not in json.dumps(projected)
    # A Chinese sentence containing 分 is untouched: this is a structured
    # projection, never a search-and-replace over prose.
    assert projected["note"] == "这件商品很划算，分两次就能买完。"


def test_tool_schema_exposes_no_money_field():
    """Money crosses to the model in yuan only; no fen amount is ever authored."""
    from app.agent.protocol import proposal_schema
    from app.agent.tools.schemas import PREPARE_PURCHASE_PLAN_INPUT_SCHEMA

    properties = PREPARE_PURCHASE_PLAN_INPUT_SCHEMA["properties"]
    assert not any(name.endswith("_fen") for name in properties)
    assert "budget_yuan" not in properties

    # The schema the model is actually given: a budget is stated in yuan, and a
    # fen amount is refused by the parser (``FORBIDDEN_KEYS``), so no ``*_fen``
    # field is advertised anywhere in it.
    advertised = json.dumps(proposal_schema(), ensure_ascii=False)
    assert "_fen" not in advertised
    assert "budget_yuan" in advertised


def test_every_demo_product_is_sellable_after_seeding(tmp_path):
    """A demo SKU without an offer is listed but unbuyable — the worst of both.

    The production session factory disables autoflush, so the default-price pass
    must flush the products it inserted earlier in the same transaction.
    """
    import sys

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import cart, catalog, conversation, session as session_models, store, trace  # noqa: F401
    from app.models.catalog import CatalogProduct
    from app.models.store import Offer

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from scripts.seed_runtime import (
        ensure_catalog_schema,
        seed_chinese_dish_templates,
        seed_demo_products,
        seed_reviews,
        seed_store_offers,
        seed_templates,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'seed.sqlite3'}")
    Base.metadata.create_all(bind=engine)
    ensure_catalog_schema(engine)
    # Mirrors the application wiring, autoflush off.
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()
    try:
        seed_demo_products(db)
        seed_reviews(db)
        seed_store_offers(db)
        seed_templates(db)
        seed_chinese_dish_templates(db)
        db.commit()
        approved = db.query(CatalogProduct).filter_by(review_status="approved").all()
        assert approved, "no approved products were seeded"
        for product in approved:
            offer = (
                db.query(Offer)
                .filter_by(store_id="store-demo-01", sku_id=product.sku_id)
                .first()
            )
            assert offer is not None, f"{product.sku_id} seeded without an offer"
            assert offer.sellable, f"{product.sku_id} seeded as not sellable"
    finally:
        db.close()


# ------------------------------------------------ cart integration regressions


def _patch_plan(client, task_id: str, **changes):
    db = _db(client)
    row = db.execute(
        text("SELECT plan_json FROM guide_tasks WHERE task_id = :t"), {"t": task_id}
    ).fetchone()
    plan = json.loads(row[0])
    plan.update(changes)
    db.execute(
        text("UPDATE guide_tasks SET plan_json = :p WHERE task_id = :t"),
        {"p": json.dumps(plan), "t": task_id},
    )
    db.commit()
    return plan


def test_row_add_rejects_a_cart_from_another_store(client, semantic_provider):
    """The row path must not write into a cart that belongs to a different store."""
    from app.models.cart import Cart

    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    db = _db(client)
    owner = _owner(client)
    db.query(Cart).delete()
    db.add(Cart(owner_id=owner, store_id="store-elsewhere", version=1))
    db.commit()

    response = add_row(client, body, tomato["sku_id"], 1)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STORE_MISMATCH"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_row_add_requires_a_refresh_after_a_supply_change(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    _patch_plan(client, body["task_id"], validation_status="stale_supply", can_confirm=False)

    response = add_row(client, body, tomato["sku_id"], 1)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_SUPPLY"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_row_add_enforces_the_stated_budget_in_yuan(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    db = _db(client)
    task = db.execute(
        text("SELECT requirements_json FROM guide_tasks WHERE task_id = :t"),
        {"t": body["task_id"]},
    ).fetchone()
    requirements = json.loads(task[0])
    requirements["budget_fen"] = 1
    db.execute(
        text("UPDATE guide_tasks SET requirements_json = :r WHERE task_id = :t"),
        {"r": json.dumps(requirements), "t": body["task_id"]},
    )
    db.commit()

    response = add_row(client, body, tomato["sku_id"], 1)
    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert "预算" in message and "元" in message
    assert str(tomato["unit_price_fen"]) not in message, "raw fen leaked"
    assert client.get("/api/v1/cart").json()["items"] == []


def test_row_add_still_works_for_a_row_the_plan_flagged_unconfirmable(
    client, semantic_provider
):
    """A disabled plan flag must not block an explicit click on another row."""
    body = plan_for(client, semantic_provider)
    _patch_plan(client, body["task_id"], can_confirm=False)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    response = add_row(client, body, tomato["sku_id"], 1)
    assert response.status_code == 200, response.text


def test_refresh_keeps_the_row_add_ledger(client, semantic_provider):
    """Re-pricing must not forget what was already bought one by one."""
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    added = add_row(client, body, tomato["sku_id"], tomato["quantity"])
    assert added.status_code == 200, added.text
    payload = added.json()

    refreshed = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-refresh",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_state_version": payload["state_version"],
            "expected_session_version": payload["session_version"],
            "base_plan_id": payload["plan_id"],
            "base_plan_version": payload["plan_version"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    data = refreshed.json()
    row = next(i for i in data["items"] if i["sku_id"] == tomato["sku_id"])
    assert row["added_quantity"] == tomato["quantity"], "refresh dropped the ledger"
    assert row["remaining_quantity"] == 0

    remaining = [
        {"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
        for i in data["items"]
        if i.get("selected", True) and i.get("remaining_quantity", 0) > 0
    ]
    if remaining:
        result = client.post(
            f"/api/v1/guide/tasks/{body['task_id']}/confirm",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "plan_id": data["plan_id"],
                "plan_version": data["plan_version"],
                "expected_state_version": data["state_version"],
                "expected_session_version": data["session_version"],
                "selected_items": remaining,
            },
        )
        assert result.status_code == 200, result.text
    cart = client.get("/api/v1/cart").json()
    total = sum(i["quantity"] for i in cart["items"] if i["sku_id"] == tomato["sku_id"])
    assert total == tomato["quantity"], f"bought twice after refresh: {total}"


def test_revision_after_a_row_add_uses_the_remaining_headroom(
    client, semantic_provider
):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    added = add_row(client, body, tomato["sku_id"], 1)
    assert added.status_code == 200, added.text
    payload = added.json()

    revised = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": payload["session_version"],
            "expected_state_version": payload["state_version"],
            "base_plan_id": payload["plan_id"],
            "base_plan_version": payload["plan_version"],
            "client_edit_sequence": 1,
            "items": [
                {
                    "sku_id": i["sku_id"],
                    "quantity": i["quantity"],
                    "selected": i.get("selected", True),
                }
                for i in payload["items"]
            ],
        },
    )
    assert revised.status_code == 200, revised.text
    row = next(i for i in revised.json()["items"] if i["sku_id"] == tomato["sku_id"])
    assert row["added_quantity"] == 1


def test_alternatives_confirm_never_rebuys_an_added_row(client, semantic_provider):
    body = plan_for(client, semantic_provider)
    tomato = next(i for i in body["plan"]["items"] if "tomato" in i["sku_id"])
    added = add_row(client, body, tomato["sku_id"], tomato["quantity"])
    assert added.status_code == 200, added.text
    payload = added.json()
    _patch_plan(client, body["task_id"], mode="alternatives")

    result = client.post(
        f"/api/v1/guide/tasks/{body['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": payload["plan_id"],
            "plan_version": payload["plan_version"],
            "expected_state_version": payload["state_version"],
            "expected_session_version": payload["session_version"],
            "selected_items": [{"sku_id": tomato["sku_id"], "quantity": tomato["quantity"]}],
        },
    )
    assert result.status_code == 422, result.text
    cart = client.get("/api/v1/cart").json()
    total = sum(i["quantity"] for i in cart["items"] if i["sku_id"] == tomato["sku_id"])
    assert total == tomato["quantity"], "the alternative was bought twice"


def test_summary_is_short_and_does_not_re_ask_people_for_a_drink(
    client, semantic_provider
):
    """The panel carries the list and the prices; the message stays factual.

    A headcount note belongs to the dish that was just prepared — never to the
    turn that adds a bottle of cola, which must not re-ask about people.
    """
    semantic_provider(
        [
            *lookup_then_add_id("dish", "番茄炒蛋", TOMATO, people=2),
            *lookup_then_add_id("product", "可乐 330毫升", COLA_SKU, relation="append"),
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋，2人").json()

    message = first["message"]
    assert "番茄炒蛋" in message and "¥" in message
    # The dish that was just prepared carries its headcount note.
    assert "2 人份" in message, message
    # No repeated instruction about checkboxes, quantities or clicking confirm.
    for instruction in ("可以勾选", "改件数", "加入购物车", "点击确认", "只有你点击"):
        assert instruction not in message, message

    second = turn(client, sid, "还要一瓶可乐", first).json()
    assert second["plan"], second
    follow_up = second["message"]
    assert "可乐" in follow_up
    assert "¥" in follow_up
    # The drink is a product group, not a dish this turn committed: the older
    # dish's headcount must not be repeated for it.
    assert "人份" not in follow_up, "the drink turn must not re-ask about people"
    assert "默认" not in follow_up, "the drink turn repeated the dish's headcount note"


# ------------------------------------------- merge metadata: gap preservation


def _merge_target(db, group_id: str, sku_id: str, *, price_fen: int = 100, gaps=None, available_qty: int = 20) -> dict:
    """A minimal validated plan shape backed by a real synthetic offer."""
    from app.models.catalog import CatalogProduct
    from app.models.store import Offer

    if db.get(CatalogProduct, sku_id) is None:
        db.add(
            CatalogProduct(
                sku_id=sku_id,
                name=sku_id,
                name_zh=sku_id,
                category_id="demo",
                review_status="approved",
                ingredient_ids=json.dumps([sku_id]),
                spec_quantity=500,
                spec_unit="g",
            )
        )
    if db.query(Offer).filter_by(store_id="store-demo-01", sku_id=sku_id).first() is None:
        db.add(
            Offer(
                store_id="store-demo-01",
                sku_id=sku_id,
                price_fen=price_fen,
                available_qty=available_qty,
                sellable=True,
            )
        )
    db.commit()
    target_id = group_id.split(":", 1)[1]
    requirement = {
        "required_item_id": f"{group_id}#main",
        "ingredient_id": sku_id,
        "component_id": None,
        "name": "merge_thing",
        "quantity": 500.0,
        "unit": "g",
        "quantity_known": True,
        "requiredness": "core",
        "source": {"kind": "local_recipe", "ref": group_id},
    }
    return {
        "plan_id": f"plan-{target_id}",
        "plan_version": 1,
        "coverage_intent": "partial_ok",
        "gaps": list(gaps or []),
        "target": {
            "group_id": group_id,
            "kind": "dish",
            "target_id": target_id,
            "name": target_id,
        },
        "items": [
            {
                "sku_id": sku_id,
                "name": sku_id,
                "quantity": 1,
                "unit_price_fen": price_fen,
                "line_total_fen": price_fen,
                "recommended_quantity": 1,
                "quantity_source": "recommended",
                "role": "required",
                "selected": True,
                "group_id": group_id,
                "availability": "available",
                "max_addable_quantity": available_qty,
                "required_item_id": f"{group_id}#main",
                "requirement": requirement,
                "pack_source": "catalog_spec",
            }
        ],
    }


def _not_found(group_id: str, ingredient_id: str) -> dict:
    from app.services import plan_contract

    return plan_contract.make_gap(
        group_id=group_id,
        target_kind="dish",
        target_id=group_id.split(":", 1)[1],
        kind="not_found",
        ingredient_id=ingredient_id,
        name=ingredient_id,
        required_item_id=f"{group_id}#{ingredient_id}",
    )


def test_merge_keeps_a_new_plans_own_gaps(db_session):
    """A fresh plan must persist the gaps its own rows proved (the P0 data-loss fix)."""
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    merged = service.merge_plan(
        None,
        _merge_target(db_session, "dish:a", "p0:merge-a", gaps=[_not_found("dish:a", "basil")]),
        group_id="dish:a",
        operation="replace",
    )
    assert {g["ingredient_id"] for g in merged["gaps"]} == {"basil"}, merged["gaps"]
    assert merged["coverage_mode"] == "partial", merged
    assert merged["selected_total_fen"] == 100, merged


def test_merge_replace_does_not_carry_the_replaced_plans_gaps(db_session):
    """A switch drops the old goal's rows and gaps, and keeps only the new plan's."""
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    base = service.merge_plan(
        None,
        _merge_target(db_session, "dish:a", "p0:merge-a", gaps=[_not_found("dish:a", "basil")]),
        group_id="dish:a",
        operation="replace",
    )
    assert {g["ingredient_id"] for g in base["gaps"]} == {"basil"}, base["gaps"]

    switched = service.merge_plan(
        base, _merge_target(db_session, "dish:b", "p0:merge-b"), group_id="dish:b", operation="replace"
    )
    assert switched["gaps"] == [], switched["gaps"]
    assert switched["coverage_mode"] == "full", switched
    assert {t["group_id"] for t in switched["targets"]} == {"dish:b"}, switched
    assert {i["sku_id"] for i in switched["items"]} == {"p0:merge-b"}, switched["items"]
    assert switched["selected_total_fen"] == 100, switched


def test_merge_append_keeps_both_targets_gaps(db_session):
    """Appending keeps the existing target's gaps and adds the new target's."""
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    base = service.merge_plan(
        None,
        _merge_target(db_session, "dish:a", "p0:merge-a", gaps=[_not_found("dish:a", "basil")]),
        group_id="dish:a",
        operation="replace",
    )
    appended = service.merge_plan(
        base,
        _merge_target(db_session, "dish:b", "p0:merge-b", gaps=[_not_found("dish:b", "shrimp")]),
        group_id="dish:b",
        operation="append",
    )
    assert {g["ingredient_id"] for g in appended["gaps"]} == {"basil", "shrimp"}, appended["gaps"]
    assert appended["coverage_mode"] == "partial", appended
    assert {i["sku_id"] for i in appended["items"]} == {"p0:merge-a", "p0:merge-b"}, appended["items"]
    assert appended["selected_total_fen"] == 200, appended


def test_merge_remove_retires_only_that_targets_gaps(db_session):
    """Removing a target retires its rows and gaps, never another target's."""
    from app.services.shopping_plan_service import ShoppingPlanService

    service = ShoppingPlanService(db_session)
    base = service.merge_plan(
        None,
        _merge_target(db_session, "dish:a", "p0:merge-a", gaps=[_not_found("dish:a", "basil")]),
        group_id="dish:a",
        operation="replace",
    )
    two = service.merge_plan(
        base,
        _merge_target(db_session, "dish:b", "p0:merge-b", gaps=[_not_found("dish:b", "shrimp")]),
        group_id="dish:b",
        operation="append",
    )
    removed = service.merge_plan(
        two, {"items": [], "target": {}}, group_id="dish:a", operation="remove"
    )
    assert {g["ingredient_id"] for g in removed["gaps"]} == {"shrimp"}, removed["gaps"]
    assert removed["coverage_mode"] == "partial", removed
    assert {t["group_id"] for t in removed["targets"]} == {"dish:b"}, removed
    assert {i["sku_id"] for i in removed["items"]} == {"p0:merge-b"}, removed["items"]
    assert removed["selected_total_fen"] == 100, removed

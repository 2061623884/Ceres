"""Acceptance tests for the semantic proposal pipeline — the only chain.

These exercise it end to end: the low-cardinality candidate set, the
protocol parser, the server compiler, the existing business services and the
database. Only the model provider is scripted, so no credentials and no network
are used.

What they pin down:

* a turn with no verified mutation never writes a plan and never touches the cart
* chat / recommendation / an absurd request keep the plan exactly as it is
* an add merges into the existing plan instead of replacing it
* empty or invalid model output is reported, never dressed up as a success
* typed quantity edits respect the already-bought ledger and the stock ceiling
* a confirmed plan stays readable and is not rewritten by later chat
* SSE emits ``plan.ready`` only when a plan actually changed
"""

from __future__ import annotations

import json
import uuid

import pytest

from support import create_session, post_turn
from support.semantic_agent import (
    first_group_ref,
    first_item_ref,
    plan_group_ref,
    reply_only,
    request_amend,
    request_new,
)


def lookup_then_add(kind, query, name_fragment=None, *, purchase=True, **modifiers):
    """One-pass purchase proposal: the server resolves the named exact hit."""
    name = (
        "鲜鸡蛋 10枚装" if kind == "product" and query == "鸡蛋"
        else "可乐 330毫升" if kind == "product" and query == "可乐"
        else query
    )
    goal = (
        {"kind": "product_purchase", "target_name": name, "items": [name]}
        if kind == "product" else {"kind": "meal_plan", "target_name": name}
    )
    constraints = dict(modifiers.get("constraints") or {})
    if modifiers.get("people"):
        constraints["people"] = modifiers["people"]
    if constraints:
        goal["constraints"] = constraints
    proposal = {"lookups": [{"kind": kind, "query": name}]}
    if purchase:
        proposal["understanding"] = {
            "speech_act": "request_action", "goal_relation": "new",
            "new_goal": goal,
        }
    return [proposal]


def turn(client, session_id: str, message: str, previous: dict | None = None, *, request_id=None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=request_id or str(uuid.uuid4()))


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


def snapshot(client, session_id: str) -> dict:
    return client.get(f"/api/v1/guide/sessions/{session_id}").json()


def turn_ok(client, session_id, message, previous=None, **kwargs):
    response = turn(client, session_id, message, previous, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ the default


def test_there_is_no_pipeline_selector_left(monkeypatch):
    """The chain is not opt-in any more, and no env value can reopen the old one.

    A real ``.env`` may still carry a stale ``SEMANTIC_PIPELINE_MODE`` line; it
    must be inert because the setting itself no longer exists.
    """
    from app.core.config import Settings

    monkeypatch.delenv("SEMANTIC_PIPELINE_MODE", raising=False)
    assert not hasattr(Settings(_env_file=None), "semantic_pipeline_mode")
    monkeypatch.setenv("SEMANTIC_PIPELINE_MODE", "legacy")
    assert not hasattr(Settings(_env_file=None), "semantic_pipeline_mode")


# ------------------------------------------------------- pure conversation turns


def test_chat_turn_writes_nothing(client, semantic_provider):
    """No mutation, no task, no plan: understanding never pre-commits."""
    provider = semantic_provider([reply_only("你好，想吃点什么？")])
    sid = create_session(client)
    body = turn_ok(client, sid, "你好")

    assert body["plan_effect"] == "keep"
    assert body["plan"] is None
    assert body["task_id"] is None
    assert body["state_version"] == 0
    assert body["action_results"] == []
    assert provider.remaining() == 0


def test_chat_after_plan_keeps_the_plan(client, semantic_provider):
    semantic_provider(
        [*lookup_then_add("product", "鸡蛋"), reply_only("这份清单会一直留着，你可以随时改。")]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    assert first["plan_effect"] == "replace"
    assert first["plan"] and first["plan"]["items"]

    plan_id = first["plan"]["plan_id"]
    plan_version = first["plan"]["plan_version"]
    quantities = [i["quantity"] for i in first["plan"]["items"]]

    second = turn_ok(client, sid, "这个清单是什么意思？", first)
    assert second["plan_effect"] == "keep"
    assert second["plan"] is None
    # Nothing about the plan moved: same version, same rows, same quantities.
    assert second["state_version"] == first["state_version"]
    restored = snapshot(client, sid)["plan"]
    assert restored["plan_id"] == plan_id
    assert restored["plan_version"] == plan_version
    assert [i["quantity"] for i in restored["items"]] == quantities


def test_recommendation_query_never_writes_a_plan(client, semantic_provider):
    """The server fetches real facts; the *model* writes the answer."""
    answer = "现在能配齐的是番茄炒蛋，想直接买的话鸡蛋也有。"
    provider = semantic_provider(
        [{"queries": [{"kind": "recommend"}]}, reply_only(answer)]
    )
    sid = create_session(client)
    body = turn_ok(client, sid, "还有什么推荐的呢")

    assert body["plan_effect"] == "keep"
    assert body["plan"] is None
    assert body["task_id"] is None
    assert body["state_version"] == 0
    # No server-composed substitute for the model's words.
    assert body["message"] == answer

    read_only = [r for r in body["action_results"] if r["type"] == "read_only"]
    assert read_only, body["action_results"]
    # Read-only work is completed, and saved=False must not read as a failure.
    assert read_only[0]["status"] == "completed"
    assert read_only[0]["saved"] is False
    assert all(r.get("status") != "failed" for r in body["action_results"])

    # The second propose call carried the fetched facts back to the model.
    second = provider.requests[1]
    assert second["query_results"], second
    assert second["query_results"][0]["status"] == "completed"
    assert second["query_results"][0]["kind"] == "recommend"


def test_lookup_completion_is_reported_even_when_empty(client, semantic_provider):
    """An empty lookup is a finished lookup: the model must not loop on it."""
    provider = semantic_provider(
        [
            {"lookups": [{"kind": "product", "query": "键盘"}]},
            reply_only("店里没有键盘这种商品，吃的倒是可以帮你配。"),
        ]
    )
    sid = create_session(client)
    body = turn_ok(client, sid, "键盘")

    assert body["plan_effect"] == "keep"
    results = provider.requests[1]["query_results"]
    assert results and results[0]["kind"] == "lookup"
    assert results[0]["status"] == "completed"
    assert "empty" in results[0]
    assert body["message"].startswith("店里没有键盘")


def test_absurd_request_keeps_plan_and_does_not_order(client, semantic_provider):
    """A joke is answered as a joke: no fabricated product, no plan change."""
    semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋"),
            reply_only("键盘不能吃，不过我可以帮你配点别的。"),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    plan_version = first["plan"]["plan_version"]

    second = turn_ok(client, sid, "我想吃键盘", first)
    assert second["plan_effect"] == "keep"
    assert [r for r in second["action_results"] if r["type"] == "mutation"] == []
    assert snapshot(client, sid)["plan"]["plan_version"] == plan_version


def test_empty_model_response_is_reported_not_faked(client, semantic_provider):
    """An empty proposal is a protocol error, never a generic success line."""
    semantic_provider([{}, {}])
    sid = create_session(client)
    body = turn_ok(client, sid, "随便")

    assert "我可以帮你搭配购买方案" not in body["message"]
    assert body["plan_effect"] == "keep"
    assert body["plan"] is None
    codes = [r.get("code") for r in body["action_results"]]
    assert "EMPTY_PROPOSAL" in codes


# ------------------------------------------------------------------- mutations


def test_add_product_keeps_the_existing_dish_group(client, semantic_provider):
    semantic_provider([*lookup_then_add("dish", "番茄炒蛋", "番茄", people=2), *lookup_then_add("product", "鸡蛋")])
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃番茄炒蛋")
    assert first["plan"]["targets"], first
    groups_before = {t["group_id"] for t in first["plan"]["targets"]}

    second = turn_ok(client, sid, "再加一件商品", first)
    assert second["plan_effect"] == "replace"
    groups_after = {t["group_id"] for t in second["plan"]["targets"]}
    assert groups_before <= groups_after
    assert len(groups_after) > len(groups_before)
    assert any(r.get("saved") for r in second["action_results"])


def test_query_and_add_in_the_same_turn(client, semantic_provider):
    """Asking for a query must not cost the add that came with it."""
    # Both reads and the named goal are declared before retrieval. The mutation
    # node resolves the exact target; no second route/decision call is made.
    semantic_provider([{
        "understanding": request_new("product", "鲜鸡蛋 10枚装", relation="new"),
        "queries": [{"kind": "recommend", "query": "家常菜"}],
        "lookups": [{"kind": "product", "query": "鲜鸡蛋 10枚装"}],
    }])
    sid = create_session(client)
    body = turn_ok(client, sid, "推荐点东西，顺便买一件")

    assert body["plan_effect"] == "replace"
    assert body["plan"] and body["plan"]["items"]
    statuses = {(r["type"], r.get("status")) for r in body["action_results"]}
    assert ("mutation", "committed") in statuses
    assert ("read_only", "completed") in statuses
    assert "已经加了一件" not in body["message"]  # Pre-execution prose is not a receipt.
    assert "采购清单已加入" in body["message"]


def test_unknown_candidate_ref_is_rejected_and_plan_is_kept(client, semantic_provider):
    semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋"),
            {
                "understanding": request_new("product", "不存在的东西", relation="append"),
                "mutations": [{"verb": "add", "candidate_ref": "zz9"}],
            },
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    plan_version = first["plan"]["plan_version"]

    second = turn_ok(client, sid, "再买一个不存在的东西", first)
    assert second["plan_effect"] == "keep"
    assert any(
        r.get("code") == "UNKNOWN_CANDIDATE_REF" for r in second["action_results"]
    )
    assert snapshot(client, sid)["plan"]["plan_version"] == plan_version


def test_typed_quantity_change_and_out_of_range_refusal(client, semantic_provider):
    def change(mode, value):
        def propose(request):
            ref = first_item_ref(request)
            return {
                "understanding": request_amend(focus=ref),
                "mutations": [{"verb": "change",
                    "target_ref": ref, "field": "quantity",
                    "name": request["current_plan"]["items"][0]["name"],
                    "quantity": {"mode": mode, "value": value}}],
            }
        return propose
    semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋"),
            change("set", 2),
            change("delta", -1),
            change("delta", 500),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")

    # A typed edit either lands exactly as asked, or is refused with a bound —
    # never a partial or silently different result. The seeded stock decides
    # which of the two, so the invariant is asserted rather than one branch.
    changed = turn_ok(client, sid, "改成两件", first)
    if changed["plan_effect"] == "replace":
        assert changed["plan"]["items"][0]["quantity"] == 2
        assert changed["plan"]["items"][0]["quantity_source"] == "user"
        # "少一件" must be expressible: a delta may be negative.
        fewer = turn_ok(client, sid, "少一件", changed)
        assert fewer["plan_effect"] == "replace", fewer["action_results"]
        assert fewer["plan"]["items"][0]["quantity"] == 1
        baseline = fewer
    else:
        assert any(
            r.get("code") == "QUANTITY_OUT_OF_RANGE" for r in changed["action_results"]
        ), changed["action_results"]
        baseline = first

    # An absurd delta can never exceed the stock ceiling, whatever the stock is.
    refused = turn_ok(client, sid, "再来五百件", baseline)
    assert refused["plan_effect"] == "keep"
    assert any(
        r.get("code") == "QUANTITY_OUT_OF_RANGE" for r in refused["action_results"]
    )
    unchanged = snapshot(client, sid)["plan"]
    assert unchanged["items"][0]["quantity"] == baseline["plan"]["items"][0]["quantity"]


def test_quantity_change_accepts_a_single_sku_product_group(client, semantic_provider):
    """「这件商品改成两件」 may address the group: one group, one real row."""

    def change_group(mode, value):
        def build(request):
            group = next(
                g for g in request["current_plan"]["groups"] if g.get("target_kind") == "product"
            )
            ref = plan_group_ref(request, group["group_id"])
            return {
                "understanding": request_amend(focus=ref),
                "mutations": [{
                    "verb": "change",
                    "target_ref": ref,
                    "name": group["name"],
                    "field": "quantity",
                    "quantity": {"mode": mode, "value": value},
                }],
            }
        return build

    semantic_provider(
        [
            *lookup_then_add("dish", "番茄炒蛋", "番茄", people=2),
            # A drink, not an ingredient: the dish already owns the egg row, so
            # adding eggs would merge into it instead of forming its own group.
            *lookup_then_add("product", "可乐"),
            change_group("set", 2),
            change_group("delta", -1),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃番茄炒蛋")
    second = turn_ok(client, sid, "再加一件商品", first)
    product_group = next(t for t in second["plan"]["targets"] if t.get("kind") == "product")
    quantity_sku = product_group["target_id"]
    before = {i["sku_id"]: i["quantity"] for i in second["plan"]["items"]}

    changed = turn_ok(client, sid, "这件商品改成两件", second)
    if changed["plan_effect"] != "replace":
        # Seeded stock decides whether the absolute count lands; a refusal must be
        # typed, and it must leave every row exactly where it was.
        assert any(
            r.get("code") == "QUANTITY_OUT_OF_RANGE" for r in changed["action_results"]
        ), [(r.get("code"), r.get("message")) for r in changed["action_results"]]
        after = {i["sku_id"]: i["quantity"] for i in snapshot(client, sid)["plan"]["items"]}
        assert after == before
        return

    after = {i["sku_id"]: i["quantity"] for i in changed["plan"]["items"]}
    assert after[quantity_sku] == 2
    # The dish's own ingredients are untouched: the group was not read as "the
    # first row of the plan".
    assert {k: v for k, v in after.items() if k != quantity_sku} == {
        k: v for k, v in before.items() if k != quantity_sku
    }

    fewer = turn_ok(client, sid, "这件商品少一件", changed)
    assert fewer["plan_effect"] == "replace", fewer["action_results"]
    final = {i["sku_id"]: i["quantity"] for i in fewer["plan"]["items"]}
    assert final[quantity_sku] == 1
    assert {k: v for k, v in final.items() if k != quantity_sku} == {
        k: v for k, v in before.items() if k != quantity_sku
    }


def test_quantity_change_refuses_a_multi_ingredient_group(client, semantic_provider):
    """A dish group owns several rows: it is never a pack count."""

    def change_dish_group(request):
        group = next(
            g for g in request["current_plan"]["groups"] if g.get("target_kind") == "dish"
        )
        return {
            "understanding": request_amend(focus=group["ref"]),
            "mutations": [{
                "verb": "change",
                "target_ref": group["ref"],
                "name": group["name"],
                "field": "quantity",
                "quantity": {"mode": "set", "value": 2},
            }],
        }

    semantic_provider([*lookup_then_add("dish", "番茄炒蛋", "番茄", people=2), change_dish_group])
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃番茄炒蛋")
    before = snapshot(client, sid)["plan"]

    refused = turn_ok(client, sid, "这道菜改成两份", first)
    assert refused["plan_effect"] == "keep"
    assert any(
        r.get("code") == "UNSUPPORTED_OPERATION" for r in refused["action_results"]
    ), refused["action_results"]
    assert snapshot(client, sid)["plan"] == before


def test_quantity_set_and_delta_have_different_domains():
    """set is an absolute count (positive); delta is a change (may be negative)."""
    from app.agent.protocol import SemanticProtocolError, parse_proposal

    def proposal(spec):
        return {
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": "i1",
                    "field": "quantity",
                    "quantity": spec,
                }
            ]
        }

    parsed = parse_proposal(proposal({"mode": "delta", "value": -1}))
    assert parsed.mutations[0].quantity_mode == "delta"
    assert parsed.mutations[0].quantity_value == -1

    for spec in ({"mode": "set", "value": -1}, {"mode": "set", "value": 0}):
        with pytest.raises(SemanticProtocolError):
            parse_proposal(proposal(spec))

    with pytest.raises(SemanticProtocolError):
        parse_proposal(proposal({"mode": "delta", "value": 0}))


def test_budget_is_authored_in_yuan_only():
    """Money crosses the model boundary in yuan; fen is refused, not rescaled."""
    from app.agent.protocol import SemanticProtocolError, parse_proposal

    parsed = parse_proposal(
        {"reply": "好", "mutations": [{"verb": "add", "candidate_ref": "p1",
                                       "constraints": {"budget_yuan": 19.99}}]}
    )
    assert parsed.mutations[0].budget_fen == 1999

    with pytest.raises(SemanticProtocolError) as exc:
        parse_proposal(
            {"mutations": [{"verb": "add", "candidate_ref": "p1",
                            "constraints": {"budget_fen": 1999}}]}
        )
    assert exc.value.code == "FORBIDDEN_FIELD"


def test_rewriting_constraints_on_an_existing_plan_is_refused(
    client, semantic_provider
):
    """Storing a constraint the plan no longer satisfies would sell a wrong list."""
    def change_budget(request):
        group = request["current_plan"]["groups"][0]
        return {
            "understanding": request_amend(focus=group["ref"]),
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": group["ref"],
                    "name": group["name"],
                    "field": "constraints",
                    "constraints": {"budget_yuan": 10},
                }
            ],
        }

    semantic_provider([*lookup_then_add("product", "鸡蛋"), change_budget])
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    plan_version = first["plan"]["plan_version"]

    second = turn_ok(client, sid, "预算改成 10 元", first)
    assert second["plan_effect"] == "keep"
    assert any(
        r.get("code") == "UNSUPPORTED_OPERATION" for r in second["action_results"]
    ), second["action_results"]

    after = snapshot(client, sid)
    assert after["plan"]["plan_version"] == plan_version
    assert after["constraints_summary"]["budget_fen"] is None


def test_failed_action_is_visible_and_no_success_claim_is_reused(
    client, semantic_provider
):
    """Partial success is reported as partial; the model's claim is dropped."""

    def proposal(request):
        # Two edits of the *same* row: the second one is impossible, so the turn is
        # a partial success and the model's claim about it is dropped.
        ref = first_item_ref(request)
        row = request["current_plan"]["items"][0]
        return {
            "reply": "已经帮你加好了。",
            "understanding": request_amend(focus=ref),
            "mutations": [
                {
                    "verb": "change", "target_ref": ref, "name": row["name"],
                    "field": "quantity", "quantity": {"mode": "set", "value": 2},
                },
                {
                    "verb": "change", "target_ref": ref, "name": row["name"],
                    "field": "quantity", "quantity": {"mode": "set", "value": 99},
                },
            ],
        }

    semantic_provider(
        [*lookup_then_add("product", "鸡蛋"), proposal]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买一件")
    body = turn_ok(client, sid, "改成两件，再来很多件", first)

    # The Graph's accepted contract refuses a compound edit *whole*: a later
    # step's business failure rejects the batch, so nothing is half-applied. That
    # is stricter than the loop's partial write (see
    # tests/agent/graph/test_r2_ordered_prepare.py::test_prepare_many_rolls_back_whole_batch_on_later_failure),
    # and the safety intent here is preserved: the model's success claim is never
    # reused and the failed edit is visible in the receipts.
    assert "已经帮你加好了" not in body["message"]
    assert body["message"]
    assert body["plan_effect"] == "keep"
    assert body["plan"] is None
    statuses = {r.get("status") for r in body["action_results"]}
    assert "failed" in statuses
    assert "committed" not in statuses, body["action_results"]
    # Nothing was written: the plan this turn claimed to edit is untouched.
    after = snapshot(client, sid)
    assert after["plan"]["plan_version"] == first["plan"]["plan_version"]


def test_uncertainty_with_unknown_ref_is_reported(client, semantic_provider):
    """A question with a dropped option would show fewer choices than intended."""
    semantic_provider(
        [
            {
                "uncertainties": [
                    {
                        "slot": "dish_choice",
                        "question": "你想吃哪一道？",
                        "options": [{"candidate_ref": "zz9"}],
                    }
                ]
            }
        ]
    )
    sid = create_session(client)
    body = turn_ok(client, sid, "随便来一个")

    assert any(
        r.get("code") == "UNKNOWN_CANDIDATE_REF" for r in body["action_results"]
    )
    assert "你想吃哪一道" not in body["message"]
    assert body["pending_clarification"] is None


def test_constraints_travel_through_typed_fields(client, semantic_provider):
    provider = semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋", people=4, constraints={"budget_yuan": 99}),
            reply_only("记下了。"),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "四个人吃，预算 99 元，买点鸡蛋")
    assert first["plan_effect"] == "replace"

    turn_ok(client, sid, "知道了", first)
    # The constraint the user stated is server-stored and travels to the next
    # turn — it was never re-derived from the raw sentence.
    assert provider.requests[-1]["requirements"]["budget_fen"] == 9900


def test_remove_drops_one_group_and_keeps_the_others(client, semantic_provider):
    def remove_first_group(request):
        groups = (request.get("current_plan") or {}).get("groups") or []
        assert len(groups) >= 2, groups
        return {
            "understanding": request_amend(focus=groups[0]["ref"]),
            "mutations": [
                {"verb": "remove", "target_ref": groups[0]["ref"], "name": groups[0]["name"]}
            ],
        }

    semantic_provider(
        [*lookup_then_add("dish", "番茄炒蛋", "番茄", people=2), *lookup_then_add("product", "鸡蛋"), remove_first_group]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃番茄炒蛋")
    second = turn_ok(client, sid, "再加一件商品", first)
    groups_before = {t["group_id"] for t in second["plan"]["targets"]}

    third = turn_ok(client, sid, "把第一样去掉", second)
    assert third["plan_effect"] == "replace"
    groups_after = {t["group_id"] for t in third["plan"]["targets"]}
    assert groups_after < groups_before
    assert len(groups_after) == len(groups_before) - 1


# ------------------------------------------------------------------ transport


def test_sse_chat_turn_emits_no_plan_ready(client, semantic_provider):
    semantic_provider(
        [*lookup_then_add("product", "鸡蛋"), reply_only("这份清单不会因为聊天而变化。")]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")

    events = stream_turn(client, sid, "这个清单怎么样", first)
    types = [e["type"] for e in events]
    assert "plan.ready" not in types
    assert types[-1] == "turn.completed"
    assert events[-1]["payload"]["plan_effect"] == "keep"


def test_repeated_request_id_is_replayed_without_asking_the_model_twice(
    client, semantic_provider
):
    provider = semantic_provider([reply_only("你好")])
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    first = turn_ok(client, sid, "你好", request_id=request_id)
    second = turn_ok(client, sid, "你好", request_id=request_id)

    assert first["message"] == second["message"]
    assert first["assistant_message_id"] == second["assistant_message_id"]
    assert len(provider.requests) == 1


# ------------------------------------------------------------- confirmed history


def test_confirmed_plan_is_read_only_and_chat_keeps_it(client, semantic_provider):
    semantic_provider(
        [*lookup_then_add("product", "鸡蛋"), reply_only("这份清单已经加购，记录会保留。")]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    plan = first["plan"]
    items = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in plan["items"]
        if i.get("selected", True)
    ]

    confirmed = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": "semantic-confirm-1"},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": first["state_version"],
            "expected_session_version": first["session_version"],
            "selected_items": items,
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    after_confirm = snapshot(client, sid)
    assert after_confirm["plan_read_only"] is True
    assert after_confirm["plan"]["plan_id"] == plan["plan_id"]
    assert "confirm" not in after_confirm["available_actions"]

    chat = turn_ok(client, sid, "刚才那份清单里都有什么？", after_confirm)
    assert chat["plan_effect"] == "keep"

    after_chat = snapshot(client, sid)
    assert after_chat["plan"]["plan_id"] == plan["plan_id"]
    assert after_chat["plan"]["plan_version"] == plan["plan_version"]
    assert after_chat["plan_read_only"] is True


def open_question(text: str, slot: str, *, display: bool = False):
    """A question about a row already present in the current plan."""

    def build(request):
        row = request["current_plan"]["items"][0]
        proposal: dict = {
            "uncertainties": [{
                "slot": slot,
                "question": text,
                "options": [{"candidate_ref": row["ref"]}],
            }]
        }
        if display:
            proposal["reply"] = "这几个也可以看看。"
            proposal["display_refs"] = [row["ref"]]
        return proposal

    return build


def confirm_plan(client, sid, turn_body, task_id, key):
    plan = snapshot(client, sid)["plan"]
    items = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in plan["items"]
        if i.get("selected", True)
    ]
    response = client.post(
        f"/api/v1/guide/tasks/{task_id}/confirm",
        headers={"Idempotency-Key": key},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": turn_body["state_version"],
            "expected_session_version": turn_body["session_version"],
            "selected_items": items,
        },
    )
    assert response.status_code == 200, response.text
    return plan


def test_confirming_ends_the_question_that_belonged_to_that_task(client, semantic_provider):
    """A question about a plan the shopper just bought is not still open."""
    semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋"),
            open_question("你要哪一种？", "product_choice"),
            open_question("复热时要注意什么？", "reheat"),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    asked = turn_ok(client, sid, "这两种怎么选？", first)
    assert [p["question"] for p in asked["pending_clarifications"]] == ["你要哪一种？"]

    plan = confirm_plan(client, sid, asked, first["task_id"], "semantic-confirm-pending")

    after_confirm = snapshot(client, sid)
    assert after_confirm["pending_clarifications"] == [], after_confirm["pending_clarifications"]
    # The finished task's record is untouched; only the open question is gone.
    assert after_confirm["plan"]["plan_id"] == plan["plan_id"]

    # A question raised *after* the purchase is a real open question, and it
    # survives: the questionnaire is not switched off for a finished task.
    asked_again = turn_ok(client, sid, "复热时要注意什么？", after_confirm)
    assert [p["question"] for p in asked_again["pending_clarifications"]] == ["复热时要注意什么？"]
    assert snapshot(client, sid)["pending_clarifications"] == asked_again["pending_clarifications"]


def test_new_purchase_does_not_inherit_the_previous_tasks_refs(client, semantic_provider):
    """A fresh plan starts clean: no old question, no old displayed refs."""
    def purchase_after_question(request):
        proposal = lookup_then_add("product", "鸡蛋")[0]
        proposal["resolved_questions"] = [
            item["question_id"] for item in request.get("pending_clarifications") or []
        ]
        return proposal

    provider = semantic_provider(
        [
            *lookup_then_add("product", "鸡蛋"),
            open_question("下次要不要也备一点？", "restock", display=True),
            purchase_after_question,
            reply_only("这条清单是新的一份。"),
        ]
    )
    sid = create_session(client)
    first = turn_ok(client, sid, "买点鸡蛋")
    confirm_plan(client, sid, first, first["task_id"], "semantic-confirm-refs")

    after_confirm = snapshot(client, sid)
    opened = turn_ok(client, sid, "再推荐两个？", after_confirm)
    assert opened["pending_clarifications"], opened

    # A new purchase after the finished one gets its own task...
    fresh = turn_ok(client, sid, "再买点别的", opened)
    # The switching turn still reads the finished task's context — that is where
    # the refs it is about to drop really came from.
    assert provider.requests[-1]["displayed_candidates"], provider.requests[-1]
    assert fresh["plan_effect"] == "replace"
    assert fresh["task_id"] != first["task_id"]
    assert fresh["pending_clarifications"] == []
    assert snapshot(client, sid)["pending_clarifications"] == []

    # ...and the next turn's context carries neither the old question nor the
    # refs that belonged to the finished plan.
    turn_ok(client, sid, "这条清单是什么？", fresh)
    latest = provider.requests[-1]
    assert latest.get("pending_clarifications") == []
    assert latest.get("pending_clarification") is None
    assert latest.get("displayed_candidates") == []

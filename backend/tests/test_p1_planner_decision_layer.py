"""P1 planner/decision layer, driven through the real loop, executor and API.

Every turn here is a scripted *semantic* proposal (``ScriptedSemanticProvider``),
consumed by the real ``run_loop`` → gate → executor → business services →
SQLite → HTTP response chain. The scripts are test doubles for the *model*, not
for the gate: the refs they use are the ones the server really issued, and the
assertions are about what the server did with them.

The cases mirror the review document's §9 A-E and the §10 safety assertions:
a read-only or clarifying turn writes nothing, a pending goal keeps its switch
intent while its slots are filled, a switch builds its own plan without migrating
the old one, and a contradictory or unbuildable goal is refused rather than
half-applied.

The one reading the scripts do is server-issued data (``focus_refs``, candidate
names). Nothing here asserts model quality — that is the L2 live eval.
"""

from __future__ import annotations

import uuid

from support import create_session, post_turn, post_turn
from support.semantic_agent import lookup_matches

#: A real dish and a real scenario, both seeded by ``scripts/seed_runtime.py``.
WINGS = "dish-kele-jichi"


def lookup_then_add_id(kind, query, target_id, *, people=None):
    """One-pass named goal: the mutation node binds an exact retrieved target."""
    name = "可乐 330毫升" if target_id == "demo:cola-330ml" else query
    goal = (
        {"kind": "product_purchase", "target_name": name, "items": [name]}
        if kind == "product"
        else {"kind": "meal_plan", "target_name": name}
    )
    if people:
        goal["constraints"] = {"people": people}
    return [{
        "understanding": {"speech_act": "request_action", "goal_relation": "new", "new_goal": goal},
        "lookups": [{"kind": kind, "query": name}],
    }]


def send(client, sid, text, previous=None, *, headers=None):
    del headers  # SSE entry has no extra headers in tests
    previous = previous or {}
    response = post_turn(
        client,
        sid,
        text,
        previous,
        request_id=str(uuid.uuid4()),
    )
    assert response.status_code == 200, response.json()
    return response.json()


def snapshot(client, sid):
    return client.get(f"/api/v1/guide/sessions/{sid}").json()


def plan_names(body):
    return " ".join(i.get("name") or "" for i in (body.get("plan") or {}).get("items", []))


def then(provider, *proposals):
    """Replace the rest of the script — and fail loudly if the old one desynced."""
    assert provider.remaining() == 0, f"脚本没有按预期消费完，还剩 {provider.remaining()} 步"
    provider.proposals = list(proposals)


def committed_mutations(body):
    return [r for r in body.get("action_results", []) if r.get("status") == "committed"]


# --------------------------------------------------------------------- scripts


def hotpot_goal(*, people=None, with_mode=False):
    goal = {"kind": "meal_plan", "target_name": "火锅"}
    if with_mode:
        goal["fulfillment_mode"] = "self_cook"
    goal["constraints"] = {"people": people or 2}
    return goal


def switch_to_hotpot(
    *,
    people=None,
    relation="switch",
    focus="active-goal-1",
    changes=None,
    with_mode=False,
    reply="好，换成火锅。",
):
    """A switch (or an append) of the main goal, with a real scenario ref."""

    def build(request):
        scenario = next(
            (s for s in request["candidates"]["scenarios"] if s["name"] == "火锅"), None
        )
        assert scenario, request["candidates"]["scenarios"]
        mutation = {
            "verb": "add",
            "candidate_ref": scenario["ref"],
            "name": scenario["name"],
        }
        if people:
            mutation["people"] = people
        understanding = {
            "speech_act": "correct" if relation == "switch" else "request_action",
            "goal_relation": relation,
        }
        if focus is not None:
            # Only ever a ref the server issued this turn; a new goal with nothing
            # to relate to does not name one.
            understanding["focus_ref"] = focus
        if changes is not None:
            understanding["changes"] = changes
        else:
            understanding["new_goal"] = hotpot_goal(people=people, with_mode=with_mode)
        return {"reply": reply, "understanding": understanding, "mutations": [mutation]}

    return build


def answer_pending_goal(**changes):
    """Answer the server's question about the goal under discussion."""

    def build(request):
        ref = next(
            (f["ref"] for f in request.get("focus_refs") or [] if f.get("kind") == "pending_goal"),
            None,
        )
        assert ref, f"没有待确认目标候选: {request.get('focus_refs')}"
        return {
            "reply": "好，自己煮。",
            "understanding": {
                "speech_act": "answer_clarification",
                "goal_relation": "amend",
                "focus_ref": ref,
                "changes": {"set": changes},
            },
        }

    return build


def resize_people(people, *, focus="active-goal-1", declared=None):
    """A headcount correction on the plan on screen."""

    def build(request):
        group = (request["current_plan"] or {}).get("groups", [])[0]
        return {
            "reply": "好，按新人数重新配。",
            "understanding": {
                "speech_act": "correct",
                "goal_relation": "amend",
                "focus_ref": group["ref"] if focus is None else focus,
                "changes": {"set": {"people": people if declared is None else declared}},
            },
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": group["ref"],
                    "name": group["name"],
                    "field": "people",
                    "people": people,
                }
            ],
        }

    return build


def read_only_question(text, query="鸡胸肉"):
    """An interjection the model answers without writing.

    The recommend query must overlap the offline projection: the copy runs the
    lexical route (no embedding endpoint), so a term that only a vector search
    could relate to (the original ``熟食``) returns nothing and the fixture can no
    longer assert a grounded answer. The topic is not what this test is about — it
    asserts that a read-only turn writes nothing and keeps the goal on screen — so
    it uses a real dish term from the frozen projection.
    """
    from support.semantic_agent import recommend_then_reply

    return recommend_then_reply(query, text)


# ------------------------------------------------------------------ the switch


def test_a_switch_builds_the_generic_scenario_in_one_turn(
    client, semantic_provider
):
    """§9 A/D: the switch builds the generic scenario at once; the old draft is untouched."""
    provider = semantic_provider(
        [
            *lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2),
            switch_to_hotpot(),
        ]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    assert first["plan"], first
    old_task, old_plan_id = first["task_id"], first["plan"]["plan_id"]
    old_items = {i["sku_id"] for i in first["plan"]["items"]}

    second = send(client, sid, "不是鸡翅，是火锅", first)
    assert second["route"] == "prepare"
    assert "fulfillment_mode" not in (second.get("missing_slots") or [])

    third = second
    assert third["plan"], third
    assert not third["pending_clarifications"]
    assert third["plan"]["plan_id"] != old_plan_id
    assert third["task_id"] != old_task, "a switch opens its own task"
    assert old_items.isdisjoint({i["sku_id"] for i in third["plan"]["items"]}), (
        "no row of the replaced plan may be migrated into the new one"
    )
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_switch_refuses_to_edit_the_plan_it_replaces(client, semantic_provider):
    """§10.4: Gate says switch, proposal edits the old group → nothing is written."""
    provider = semantic_provider([*lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2)])
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")

    def conflicting_switch(request):
        group = (request["current_plan"] or {}).get("groups", [])[0]
        proposal = switch_to_hotpot(with_mode=True, people=3)(request)
        proposal["understanding"]["focus_ref"] = group["ref"]
        proposal["mutations"].append(
            {
                "verb": "change",
                "target_ref": group["ref"],
                "name": group["name"],
                "field": "people",
                "people": 3,
            }
        )
        return proposal

    then(provider, conflicting_switch)
    second = send(client, sid, "不是鸡翅，是火锅，3人", first)
    assert second["plan_effect"] == "keep", second
    persisted = snapshot(client, sid)["plan"]
    assert persisted["plan_id"] == first["plan"]["plan_id"]
    assert persisted["targets"][0]["people"] == 2
    assert any(
        r.get("code") == "GOAL_CHANGE_CONFLICT" for r in second["action_results"]
    ), second["action_results"]


def test_an_amend_resizes_in_place_instead_of_switching(client, semantic_provider):
    """§9 D: the same correction word may amend — and then nothing is replaced."""
    semantic_provider(
        [
            *lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2),
            resize_people(3),
        ]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    second = send(client, sid, "不是两人，是三人", first)

    assert second["plan_effect"] == "replace", second
    assert second["task_id"] == first["task_id"], "an amendment keeps its own task"
    assert second["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert second["plan"]["targets"][0]["people"] == 3
    assert second["route"] == "apply_mutation"


def test_an_undeclared_value_never_overrides_the_declared_patch(client, semantic_provider):
    """A patch and a low-level edit that disagree are refused, not reconciled."""
    provider = semantic_provider(
        [*lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2)]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    then(provider, resize_people(4, declared=2))
    second = send(client, sid, "改成三个人", first)
    assert second["plan_effect"] == "keep", second
    assert snapshot(client, sid)["plan"]["targets"][0]["people"] == 2
    assert any(
        r.get("code") == "GOAL_CHANGE_CONFLICT" for r in second["action_results"]
    ), second["action_results"]


# -------------------------------------------------- read-only and clarification


def test_a_read_only_turn_writes_nothing_and_keeps_the_candidate(
    client, semantic_provider
):
    """§9 C: an interjection answers, and the goal under discussion survives."""
    provider = semantic_provider(
        [
            *lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2),
            switch_to_hotpot(),
            lambda _r: {
                "reply": "有的，店里也有熟食。",
                "understanding": {"speech_act": "ask_fact"},
            },
        ]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    second = send(client, sid, "不是鸡翅，是火锅", first)
    assert second["plan"], second

    third = send(client, sid, "有熟食吗", second)
    assert third["plan_effect"] == "keep", third
    assert snapshot(client, sid)["plan"]["plan_id"] == second["plan"]["plan_id"]
    assert third["route"] in ("answer", "chat", "clarify"), third["route"]
    assert third["route"] != "prepare"
    assert snapshot(client, sid)["plan"]["targets"][0]["kind"] == "scenario"


def test_a_chat_turn_with_a_mutation_writes_nothing(client, semantic_provider):
    """§10.1: chat is not a purchase, whatever else the proposal carries."""
    provider = semantic_provider([{
        "understanding": {
            "speech_act": "request_action", "goal_relation": "new",
            "new_goal": {"kind": "meal_plan", "target_name": "可乐鸡翅",
                         "constraints": {"people": 2}},
        },
        "lookups": [{"kind": "dish", "query": "可乐鸡翅"}],
    }])
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")

    def chat_with_mutation(request):
        row = lookup_matches(request, "dish")[0] if request.get("query_results") else None
        assert row is None or row
        scenario = request["candidates"]["scenarios"][0]
        return {
            "reply": "火锅是川渝一带很常见的吃法。",
            "understanding": {"speech_act": "chat"},
            "mutations": [
                {"verb": "add", "candidate_ref": scenario["ref"], "name": scenario["name"]}
            ],
        }

    then(provider, chat_with_mutation)
    second = send(client, sid, "火锅是什么", first)
    assert second["plan_effect"] == "keep", second
    assert snapshot(client, sid)["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert second["route"] == "chat"
    assert second["message"] == "火锅是川渝一带很常见的吃法。"
    assert not any(
        r.get("code") == "WRITE_BLOCKED" for r in second["action_results"]
    ), second["action_results"]
    assert committed_mutations(second) == []


def test_an_unlocated_correction_asks_instead_of_touching_the_plan(
    client, semantic_provider
):
    """§9 B: nothing was established, so nothing may be created."""
    semantic_provider(
        [
            {
                "reply": "请问你是说哪一份清单？",
                "understanding": {
                    "speech_act": "correct",
                    "goal_relation": "amend",
                    "changes": {"set": {"people": 3}},
                },
            }
        ]
    )
    sid = create_session(client)
    body = send(client, sid, "三个人")
    assert body["plan"] is None, body
    assert body["plan_effect"] == "keep"
    assert body["route"] == "clarify"
    assert body["missing_slots"] == ["focus"]
    assert body["pending_clarifications"], body


# --------------------------------------------------------------- goal building


def test_a_ready_goal_is_built_by_the_business_services(client, semantic_provider):
    """§9 E: one semantic statement, one compiled plan, one goal change."""
    semantic_provider(
        [
            switch_to_hotpot(
                people=3, with_mode=True, relation="new", focus=None
            )
        ]
    )
    sid = create_session(client)
    body = send(client, sid, "自煮3人火锅，川渝的")
    assert body["plan"], body
    assert body["plan"]["targets"][0]["target_id"] == "hotpot"
    assert body["plan"]["targets"][0]["people"] == 3
    assert body["plan"]["items"]
    assert body["route"] == "prepare"
    assert len(committed_mutations(body)) == 1, body["action_results"]
    assert body["plan"]["coverage_mode"] in ("full", "partial")


def test_a_named_hotpot_is_built_as_its_own_dish(client, semantic_provider):
    """Each named hotpot is a dish target of its own, not a hotpot variant."""
    named = {
        "川渝火锅": "dish-chuanyu-huoguo",
        "潮汕牛肉火锅": "dish-chaoshan-niurou-huoguo",
        "清汤火锅": "dish-qingtang-huoguo",
        "贵州酸汤火锅": "dish-guizhou-suansoup-huoguo",
    }
    for name, dish_id in named.items():
        semantic_provider(lookup_then_add_id("dish", name, dish_id, people=4))
        sid = create_session(client)
        body = send(client, sid, name)
        assert body["plan"], (name, body)
        target = body["plan"]["targets"][0]
        assert target["kind"] == "dish", (name, target)
        assert target["target_id"] == dish_id, (name, target)
        assert target["name"] == name, (name, target)


def test_an_unbuildable_goal_keeps_the_plan_it_could_not_replace(
    client, semantic_provider
):
    """A failed build is reported; the old task stays active and untouched."""
    provider = semantic_provider([*lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2)])
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")

    def switch_to_nothing(request):
        return {
            "reply": "好，换成那个。",
            "understanding": {
                "speech_act": "correct",
                "goal_relation": "switch",
                "new_goal": {
                    "kind": "meal_plan",
                    "fulfillment_mode": "self_cook",
                    "target_name": "并不存在的菜",
                    "constraints": {"people": 2},
                },
            },
        }

    then(provider, switch_to_nothing)
    second = send(client, sid, "改成并不存在的菜", first)
    assert second["task_id"] == first["task_id"], "a failed build must not activate"
    assert snapshot(client, sid)["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert second["plan_effect"] == "keep"
    assert any(
        r.get("code") == "GOAL_TARGET_UNRESOLVED" for r in second["action_results"]
    ), second["action_results"]


def test_a_mixed_goal_change_is_refused_whole(client, semantic_provider):
    """§10.7: one goal-level change per turn; a mixed batch writes nothing."""
    provider = semantic_provider([*lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2)])
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")

    def two_goals(request):
        scenarios = request["candidates"]["scenarios"]
        return {
            "reply": "两个都加上。",
            "understanding": {
                "speech_act": "request_action",
                "goal_relation": "append",
                "new_goal": {
                    "kind": "meal_plan",
                    "fulfillment_mode": "self_cook",
                    "target_name": scenarios[0]["name"],
                    "constraints": {"people": 2},
                },
            },
            "mutations": [
                {"verb": "add", "candidate_ref": s["ref"], "name": s["name"]}
                for s in [*scenarios[:1], *request["candidates"]["dishes"][:1]]
            ],
        }

    then(provider, two_goals)
    second = send(client, sid, "再加两样", first)
    assert second["plan_effect"] == "keep", second
    assert snapshot(client, sid)["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert any(
        r.get("status") == "blocked" for r in second["action_results"]
    ), second["action_results"]
    assert second["pending_clarifications"], second
    assert committed_mutations(second) == []


def test_a_restricted_product_delta_is_applied_exactly_once(client, semantic_provider):
    """§9 E: a stated pack count is compiled by the server, once, from a real ref."""
    provider = semantic_provider(
        [*lookup_then_add_id("product", "可乐", "demo:cola-330ml")]
    )
    sid = create_session(client)
    first = send(client, sid, "买可乐 330毫升")
    assert first["plan"], first
    row = first["plan"]["items"][0]
    before = int(row["quantity"])

    def add_four(request):
        item = (request["current_plan"] or {}).get("items", [])[0]
        return {
            "reply": "好，再加 4 瓶。",
            "understanding": {
                "speech_act": "request_action",
                "goal_relation": "amend",
                "focus_ref": item["ref"],
            },
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": item["ref"],
                    "name": item["name"],
                    "field": "quantity",
                    "quantity": {"mode": "delta", "value": 4},
                }
            ],
        }

    then(provider, add_four)
    second = send(client, sid, "再加 4 瓶", first)
    after = next(
        i for i in second["plan"]["items"] if i["sku_id"] == row["sku_id"]
    )
    assert int(after["quantity"]) == before + 4, after
    assert len(committed_mutations(second)) == 1, second["action_results"]
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_switch_leaves_the_cart_and_the_confirmation_history_alone(
    client, semantic_provider
):
    """§8: plan ≠ cart. A switch is not a purchase and not a cancellation."""
    provider = semantic_provider(
        [
            *lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2),
            switch_to_hotpot(people=3, with_mode=True),
        ]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    confirm = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": first["plan"]["plan_id"],
            "plan_version": first["plan"]["plan_version"],
            "expected_state_version": first["state_version"],
            "expected_session_version": first["session_version"],
            "selected_items": [
                {"sku_id": i["sku_id"], "quantity": i["quantity"]}
                for i in first["plan"]["items"]
                if i.get("selected", True)
            ],
        },
    )
    assert confirm.status_code == 200, confirm.text
    cart_before = client.get("/api/v1/cart").json()
    assert cart_before["items"]

    second = send(client, sid, "改做火锅", confirm.json())
    assert second["plan"], second
    assert client.get("/api/v1/cart").json()["items"] == cart_before["items"], (
        "switching a plan must not rewrite what was already bought"
    )
    assert second["task_id"] != first["task_id"]


def test_a_legacy_proposal_keeps_its_structural_path_but_cannot_switch(
    client, semantic_provider
):
    """The compatibility policy: old proposals parse, but they never write."""
    provider = semantic_provider(
        [
            *lookup_then_add_id("dish", "可乐鸡翅", WINGS, people=2),
        ]
    )
    sid = create_session(client)
    first = send(client, sid, "我想吃可乐鸡翅，2人")
    plan_id = snapshot(client, sid)["plan"]["plan_id"]

    def legacy_add(request):
        scenario = request["candidates"]["scenarios"][0]
        return {
            "reply": "已经换成火锅了。",
            "mutations": [
                {"verb": "add", "candidate_ref": scenario["ref"], "name": scenario["name"]}
            ],
        }

    then(provider, legacy_add)
    second = send(client, sid, "换成火锅", first)
    # No understanding, no write: the old proposal still parses, and nothing of it
    # is executed — not even the prose that claimed it was.
    assert snapshot(client, sid)["plan"]["plan_id"] == plan_id
    assert snapshot(client, sid)["plan"]["targets"][0]["target_id"] == WINGS
    assert not any(
        r.get("status") == "committed" for r in second["action_results"]
    ), second["action_results"]
    assert (
        any(
            r.get("reason_code") == "MISSING_UNDERSTANDING"
            for r in second.get("action_results") or []
        )
        or "understanding" in (second.get("missing_slots") or [])
        or any(
            q.get("slot") == "understanding"
            for q in second.get("pending_clarifications") or []
        )
    ), second
    assert "已经换成火锅了" not in second["message"]

    def legacy_switch(request):
        scenario = request["candidates"]["scenarios"][0]
        return {
            "reply": "换掉了。",
            "mutations": [
                {
                    "verb": "add",
                    "candidate_ref": scenario["ref"],
                    "name": scenario["name"],
                    "switch_goal": True,
                }
            ],
        }

    then(provider, legacy_switch)
    third = send(client, sid, "换成火锅", second)
    assert third["plan_effect"] == "keep", third
    assert snapshot(client, sid)["plan"]["plan_id"] == plan_id
    assert not any(
        r.get("status") == "committed" for r in third["action_results"]
    ), third["action_results"]

"""Independent acceptance probes: state boundaries, not model-quality claims."""
from __future__ import annotations

import copy
import json
import uuid

import pytest

from support import create_session, post_turn
from support.semantic_agent import (
    request_amend,
    request_new,
    reply_only,
)


def send(client, sid, text, previous=None):
    response = post_turn(client, sid, text, previous)
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(client, sid):
    response = client.get(f"/api/v1/guide/sessions/{sid}")
    assert response.status_code == 200, response.text
    return response.json()


def question():
    return {"questions": [{
        "slot": "product_choice", "question": "你想要哪一种？",
    }]}


def named_purchase(name="鸡蛋", *, relation="new"):
    """A single Proposal: decide the purchase before its real lookup runs."""
    exact = {"鸡蛋": "鲜鸡蛋 10枚装", "可乐": "可乐 330毫升"}.get(name, name)
    return {**request_new("product", exact, relation=relation),
            "lookups": [{"kind": "product", "query": exact}]}


def test_a_question_alongside_a_write_clarifies_and_writes_nothing(client, semantic_provider):
    # Rule 3: questions + any write -> clarify MODEL_QUESTION, nothing written.
    semantic_provider([{**named_purchase(), **question()}])
    sid = create_session(client)
    body = send(client, sid, "买这个，另外一种你问我一下")
    assert body["route"] == "clarify", (body["route"], body["action_results"], body["message"])
    assert body["plan_effect"] == "keep", body
    assert body["plan"] is None, body
    assert body["pending_clarifications"], body
    restored = snapshot(client, sid)
    assert restored["plan"] is None, restored
    assert restored["pending_clarifications"], restored


def test_taskless_question_survives_restore_and_next_turn(client, semantic_provider):
    provider = semantic_provider(
        [{**question(), "reply": "你想要哪一种？"}, reply_only("我还记得刚才的问题。")]
    )
    sid = create_session(client)
    first = send(client, sid, "这两种怎么选？")
    assert first["plan"] is None
    pending = first["pending_clarifications"]
    assert pending
    restored = snapshot(client, sid)
    assert restored.get("pending_clarifications") == pending
    send(client, sid, "等一下", restored)
    context = provider.requests[-1]
    assert context.get("pending_clarifications") or context.get("pending_clarification")


def test_unknown_uncertainty_ref_is_not_silently_dropped(client, semantic_provider):
    invalid = {"questions": [{"slot": "choice", "question": "选一个？",
               "options": ["made-up-ref"]}]}
    semantic_provider([invalid])
    sid = create_session(client)
    body = send(client, sid, "要哪个？")
    assert body["plan_effect"] == "keep"
    assert not body["pending_clarifications"]
    assert any(r.get("code") == "UNKNOWN_CANDIDATE_REF" for r in body["action_results"])


def test_failed_mutation_cannot_claim_success_in_reply(client, semantic_provider):
    semantic_provider([named_purchase(), {
        "reply": "已经把不存在的商品加进清单了。",
        **request_new("product", "不存在的商品", relation="append", ref="made-up-ref"),
    }])
    sid = create_session(client)
    first = send(client, sid, "买一件")
    before = snapshot(client, sid)["plan"]
    second = send(client, sid, "再买一件", first)
    assert "已经把不存在的商品加进清单了" not in second["message"]
    assert any(r.get("status") == "failed" for r in second["action_results"])
    assert snapshot(client, sid)["plan"]["plan_id"] == before["plan_id"]
    assert second["state_version"] == first["state_version"]


def test_sse_committed_plan_is_explicit_replace(client, semantic_provider):
    semantic_provider([named_purchase()])
    sid = create_session(client)
    with client.stream("POST", f"/api/v1/guide/sessions/{sid}/turns/stream", json={
        "request_id": str(uuid.uuid4()), "message": "买一件",
        "expected_task_id": None, "expected_state_version": 0,
    }) as response:
        assert response.status_code == 200
        events = [json.loads(c.removeprefix("data: "))
                  for c in "".join(response.iter_text()).split("\n\n")
                  if c.startswith("data:")]
    ready = [e for e in events if e["type"] == "plan.ready"]
    assert len(ready) == 1
    assert ready[0]["payload"]["plan_effect"] == "replace"
    assert ready[0]["payload"]["plan"]["plan_id"] == events[-1]["payload"]["plan"]["plan_id"]


def test_change_target_cannot_point_outside_active_plan(client, semantic_provider):
    semantic_provider([named_purchase(), {
        **request_amend(focus="unissued-dish", name="番茄炒蛋",
                         changes={"set": {"people": 4}}),
        "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
    }])
    sid = create_session(client)
    first = send(client, sid, "买一件")
    before = snapshot(client, sid)["plan"]
    second = send(client, sid, "改四人份", first)
    assert second["plan_effect"] == "keep"
    assert snapshot(client, sid)["plan"]["plan_id"] == before["plan_id"]
    assert second["state_version"] == first["state_version"]
    assert not any(r.get("status") == "committed" for r in second["action_results"])


@pytest.mark.parametrize("extra", [
    {"people": 4}, {"constraints": {"budget_yuan": 20}}, {"unknown_field": "x"},
])
def test_quantity_edit_rejects_other_typed_fields(extra):
    from app.agent.protocol import SemanticProtocolError, parse_proposal
    with pytest.raises(SemanticProtocolError) as error:
        parse_proposal({"focus": {"ref": "i1"},
                        "edit": {"op": "set_quantity", "quantity": 2, **extra}})
    assert error.value.code == "MALFORMED_PROPOSAL"


def test_reference_identity_is_stable_for_same_catalog_target():
    from app.agent.protocol import CandidateSet
    first = CandidateSet()
    ref = first.allocate("product", "sku-a", "A").ref
    second = CandidateSet()
    second.allocate("product", "sku-b", "B")
    assert second.allocate("product", "sku-a", "A").ref == ref


def test_quantity_recalculation_preserves_other_rows_stock_headroom(db_session):
    from app.services.shopping_plan_service import ShoppingPlanService
    service = ShoppingPlanService(db_session)
    eggs = service.build_product_plan("", target_id="demo:eggs-fresh-6pack", quantity=2)
    tomato = service.build_product_plan("", target_id="demo:tomato-fresh-500g", quantity=1)
    assert eggs["status"] == tomato["status"] == "ok"
    egg_sku = eggs["items"][0]["sku_id"]
    tomato_sku = tomato["items"][0]["sku_id"]
    base = service.merge_plan(None, eggs, group_id=eggs["group_id"], operation="replace")
    plan = service.merge_plan(base, tomato, group_id=tomato["group_id"], operation="append",
                              cart_quantities={tomato_sku: 5})
    before = next(row for row in plan["items"] if row["sku_id"] == tomato_sku)
    changed = service.apply_row_quantity(plan, egg_sku, 3, cart_quantities={tomato_sku: 5})
    after = next(row for row in changed["items"] if row["sku_id"] == tomato_sku)
    assert after["max_addable_quantity"] == before["max_addable_quantity"]
    assert after["quantity"] == before["quantity"]


def test_remove_preserves_shared_sku_manual_quantity_and_remaining_ledger(db_session):
    from app.services.shopping_plan_service import ShoppingPlanService
    service = ShoppingPlanService(db_session)
    a = service.build_product_plan("", target_id="demo:eggs-fresh-6pack", quantity=2)
    assert a["status"] == "ok"
    a["target"]["group_id"] = "dish:a"
    a["target"]["kind"] = "dish"
    a["target"]["target_id"] = "a"
    for row in a["items"]:
        row["group_id"] = "dish:a"
        row.pop("contributions", None)
    b = copy.deepcopy(a)
    b["target"].update(group_id="dish:b", target_id="b")
    for row in b["items"]:
        row["group_id"] = "dish:b"
    plan = service.merge_plan(None, a, group_id="dish:a", operation="replace")
    plan = service.merge_plan(plan, b, group_id="dish:b", operation="append")
    sku = plan["items"][0]["sku_id"]
    plan = service.apply_row_quantity(plan, sku, 6)
    row = plan["items"][0]
    for c in row["contributions"]:
        c["added_quantity"] = 1
    row["added_quantity"] = 2
    removed = service.merge_plan(plan, {"items": [], "target": {}}, group_id="dish:a",
                                 operation="remove", cart_quantities={sku: 2})
    kept = removed["items"][0]
    assert kept["quantity"] == 6
    assert kept["quantity_source"] == "user"
    # Removing a recipe contribution does not undo the two purchased packs.
    assert kept["added_quantity"] == 2
    assert kept["remaining_quantity"] == 4
    assert {c["group_id"] for c in kept["contributions"]} == {"dish:b"}
    assert kept["contributions"][0]["added_quantity"] == 1


def test_declared_purchase_survives_retrieval(client, semantic_provider):
    """A purchase stated up front may still compile after the lookup it needed."""
    semantic_provider([named_purchase("可乐")])
    sid = create_session(client)
    body = send(client, sid, "买一瓶可乐")
    assert body["plan_effect"] == "replace"
    assert body["plan"] and body["plan"]["items"]
    assert any(r.get("status") == "committed" for r in body["action_results"])
    assert snapshot(client, sid)["plan"]["plan_id"] == body["plan"]["plan_id"]
    assert [row["sku_id"] for row in body["plan"]["items"]] == ["demo:cola-330ml"]


@pytest.mark.parametrize("payload", [
    {"target": {"kind": "dish"}},
    {"target": {"kind": "meal", "intent": "order"}},
    {"target": {"kind": "meal", "relation": "new"}},
    {"constraints": {"fulfillment_mode": "delivery"}},
    {"plan_act": "cancel"},
    {"focus": {"ref": "g1"}, "edit": {"op": "set_quantity", "quantity": 0}},
    {"focus": {"ref": "g1"}, "edit": {"op": "adjust_quantity", "quantity": 0}},
    {"focus": {"ref": "g1"}, "edit": {"op": "set_quantity", "quantity": "2"}},
    {"reads": [{"kind": "recommend", "topic": "菜" * 201}]},
])
def test_an_out_of_vocabulary_value_is_refused_not_guessed(payload):
    assert proposal_error(payload).code == "MALFORMED_PROPOSAL"


def test_legacy_purchase_requested_key_is_rejected_not_silently_dropped():
    # purchase_requested is gone (target.intent=buy carries this now); an old
    # proposal that still sends it is an unknown top-level key, not a silently
    # ignored field.
    from app.agent.protocol import SemanticProtocolError, parse_proposal

    with pytest.raises(SemanticProtocolError) as error:
        parse_proposal({"reply": "好", "purchase_requested": True})
    assert error.value.code == "MALFORMED_PROPOSAL"


def proposal_error(payload):
    from app.agent.protocol import SemanticProtocolError, parse_proposal
    with pytest.raises(SemanticProtocolError) as error:
        parse_proposal(payload)
    return error.value


def uncertainty(index):
    return {"slot": f"s{index}", "question": f"问题{index}"}


def test_proposal_accepts_every_documented_size():
    # Limits: lookups+reads <= 4, questions <= 3 (display_refs/resolved_questions
    # are shape-checked separately at <= 12; see test_unusable_reference_list_is_refused).
    from app.agent.protocol import parse_proposal
    proposal = parse_proposal({
        "questions": [uncertainty(i) for i in range(3)],
        "lookups": [{"kind": "product", "query": "可乐"}],
        "reads": [{"kind": "recommend"}, {"kind": "cart"}, {"kind": "catalog"}],
        "display_refs": [f"r{i}" for i in range(12)],
        "resolved_questions": [f"q{i}" for i in range(12)],
    })
    assert len(proposal.uncertainties) == 3
    assert len(proposal.lookups) + len(proposal.queries) == 4
    assert parse_proposal({"reply": "好", "display_refs": [], "resolved_questions": []}).reply == "好"


@pytest.mark.parametrize("payload", [
    {"questions": [uncertainty(i) for i in range(4)]},
    {"lookups": [{"kind": "product", "query": "可乐"}] * 3,
     "reads": [{"kind": "cart"}] * 2},
])
def test_oversized_proposal_is_refused_with_the_limit_code(payload):
    assert proposal_error(payload).code == "PROPOSAL_LIMIT_EXCEEDED"


@pytest.mark.parametrize("key", ["display_refs", "resolved_questions"])
@pytest.mark.parametrize("values", [
    [f"r{i}" for i in range(13)],
    ["r0", ""],
    ["r0", None],
])
def test_unusable_reference_list_is_refused(key, values):
    # These two lists are length- and shape-checked by one MALFORMED_PROPOSAL
    # branch in protocol.py, so an oversized list is *not* reported as
    # PROPOSAL_LIMIT_EXCEEDED the way mutations/lookups/queries are.
    assert proposal_error({key: values}).code == "MALFORMED_PROPOSAL"


def test_lookup_phase_does_not_precommit_an_independent_add(client, semantic_provider):
    # A buy intent that names no target, alongside reads, cannot pre-commit
    # anything: without a target there is no goal, so the reads only look.
    semantic_provider(
        [
            {"target": {"intent": "buy"},
             "reads": [{"kind": "recommend", "topic": "家常菜"}],
             "lookups": [{"kind": "product", "query": "鸡蛋"}]},
            reply_only("这些是找到的候选。"),
        ]
    )
    sid = create_session(client)
    body = send(client, sid, "买一件，顺便推荐")
    assert body["plan_effect"] == "keep"
    assert body["task_id"] is None
    assert snapshot(client, sid)["plan"] is None


def test_displayed_order_is_persisted_not_replaced_by_catalog_order(client, semantic_provider):
    def display(request):
        rows = request["current_plan"]["items"]
        assert len(rows) >= 2
        # The shopper sees the inverse of stored plan order.
        return {"reply": "给你两个选择。",
                "display_refs": [rows[-1]["ref"], rows[0]["ref"]]}
    provider = semantic_provider([
        named_purchase(), named_purchase("可乐", relation="append"), display,
        reply_only("刚才的顺序没有变。"),
    ])
    sid = create_session(client)
    first = send(client, sid, "买鸡蛋")
    second = send(client, sid, "再买可乐", first)
    displayed = send(client, sid, "给我看看这两件", second)
    shown_order = [row["ref"] for row in provider.requests[-1]["current_plan"]["items"]]
    assert "1. " in displayed["message"]
    send(client, sid, "第二个是什么？", snapshot(client, sid))
    shown = provider.requests[-1]["displayed_candidates"]
    assert [row["ref"] for row in shown] == [shown_order[-1], shown_order[0]]
    assert shown_order[-1] != shown_order[0]


def test_scenario_builds_directly_without_a_pending_question(client, semantic_provider):
    def request_scenario(request):
        scenario = request["candidates"]["scenarios"][0]
        return request_new(
            "scenario", scenario["name"], relation="new", people=4, ref=scenario["ref"]
        )

    semantic_provider([request_scenario])
    sid = create_session(client)
    first = send(client, sid, "四个人吃火锅")
    # A generic scenario is prepared in the same turn; there is no style slot.
    assert first["plan"] and first["plan"]["items"], first
    assert not first["pending_clarifications"]
    assert snapshot(client, sid)["pending_clarifications"] == []


def test_compound_remove_and_add_is_not_executed_partially(client, semantic_provider):
    def compound(request):
        group = request["current_plan"]["groups"][0]
        return {
            **request_new("product", "另一个", relation="switch", ref="missing-new-target"),
            "focus": {"ref": group["ref"], "name": group["name"]},
            "edit": {"op": "remove"},
        }
    semantic_provider([named_purchase(), compound])
    sid = create_session(client)
    first = send(client, sid, "买一件")
    second = send(client, sid, "换成另一个", first)
    assert second["plan_effect"] == "keep"
    assert snapshot(client, sid)["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert second["state_version"] == first["state_version"]
    # A batch that mixes a removal with another write is refused whole: the batch
    # names the compound refusal, and nothing was applied.
    assert any(
        r.get("code") in ("MIXED_GOAL_CHANGES", "UNSUPPORTED_OPERATION", "GOAL_CHANGE_CONFLICT")
        for r in second["action_results"]
    ), second["action_results"]
    assert not any(
        r.get("status") == "committed" for r in second["action_results"]
    ), second["action_results"]


def test_repeated_same_target_does_not_regenerate_plan(client, semantic_provider):
    semantic_provider([named_purchase(), named_purchase()])
    sid = create_session(client)
    first = send(client, sid, "买一件")
    second = send(client, sid, "就是这个", first)
    assert second["plan_effect"] == "keep"
    assert second["state_version"] == first["state_version"]
    assert snapshot(client, sid)["plan"]["plan_id"] == first["plan"]["plan_id"]


def test_echoed_completed_read_is_not_reexecuted(client, semantic_provider):
    provider = semantic_provider([{"reads": [{"kind": "recommend"}]},
        {"reads": [{"kind": "recommend"}], "reply": "这几个是真实候选，可以慢慢挑。"}])
    sid = create_session(client)
    result = send(client, sid, "推荐一下")
    assert result["plan_effect"] == "keep"
    assert result["message"] == "这几个是真实候选，可以慢慢挑。"
    assert len(provider.requests) == 2
    assert not any(r.get("status") == "failed" for r in result["action_results"])


def test_valid_ref_with_wrong_product_name_is_not_executed(client, semantic_provider):
    def wrong_name(request):
        # A ref that really came back from this turn's retrieval, paired with a
        # different product's name: identity must still be refused.
        rows = request["candidates"]["products"]
        # The goal names one product, the ref points at another: the identity
        # check must refuse rather than build whichever the ref resolves to.
        return {"reply": "可乐已经加入购物车了！",
                **request_new("product", "可乐 330毫升", relation="append", ref=rows[0]["ref"])}
    semantic_provider([named_purchase(), wrong_name])
    sid = create_session(client)
    first = send(client, sid, "买一件")
    before = snapshot(client, sid)["plan"]
    cart = client.get("/api/v1/cart").json()
    second = send(client, sid, "再加一瓶可乐", first)
    assert second["plan_effect"] == "keep"
    # The gate asks which goal was meant (GOAL_TARGET_MISMATCH) instead of building it.
    assert any(
        r.get("slot") == "goal" and r.get("status") == "needs_clarification"
        for r in second["action_results"]
    ), second["action_results"]
    assert "可乐已经加入购物车了" not in second["message"]
    assert snapshot(client, sid)["plan"] == before
    assert client.get("/api/v1/cart").json()["items"] == cart["items"]


def test_unresolved_target_ref_cannot_bypass_identity_check(client, semantic_provider):
    # A ref the server never issued cannot be adopted just because a name came
    # along with it: identity is still checked against the real candidate set.
    semantic_provider([request_new("product", "鲜鸡蛋 10枚装", ref="p1")])
    sid = create_session(client)
    result = send(client, sid, "买一件")
    assert result["plan_effect"] == "keep"
    assert result["task_id"] is None
    assert any(r.get("status") == "failed" for r in result["action_results"]), result["action_results"]


def test_even_successful_mutation_uses_real_receipt_not_model_success_claim(client, semantic_provider):
    semantic_provider([{**named_purchase(), "reply": "可乐已付款并加入购物车。"}])
    sid = create_session(client)
    cart_before = client.get("/api/v1/cart").json()
    result = send(client, sid, "买第一件")
    assert result["plan_effect"] == "replace"
    assert result["plan"]["items"][0]["name"] in result["message"]
    assert "可乐已付款并加入购物车" not in result["message"]
    assert "确认加购后才会写入购物车" not in result["message"]
    assert client.get("/api/v1/cart").json()["items"] == cart_before["items"]


def test_named_recipe_query_and_general_advice_are_read_only(client, semantic_provider):
    provider = semantic_provider([{"reads": [{"kind": "recipe", "topic": "番茄炒蛋"}]},
        reply_only("一般做法：鸡蛋炒到刚凝固就盛出。")])
    sid = create_session(client)
    result = send(client, sid, "番茄炒蛋怎么做才嫩？")
    assert result["plan_effect"] == "keep"
    assert result["task_id"] is None
    assert provider.requests[-1]["query_results"][0]["query"] == "番茄炒蛋"
    assert provider.requests[-1]["read_only"] is True
    assert result["message"].startswith("一般做法")


def test_protocol_schema_advertises_only_the_independent_dimensions():
    from app.agent.protocol import proposal_schema
    schema = proposal_schema()
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    # No whole-turn label and no low-level mutation list: the gate owns the route.
    assert not {"understanding", "speech_act", "mutations", "queries"} & set(props)
    # A read names only what to look for; the stated exclusions/budget are copied
    # onto it by the server from ``constraints``, which speaks yuan only.
    assert set(props["lookups"]["items"]["properties"]) == {"kind", "query"}
    assert "budget_fen" not in props["constraints"]["properties"]


def test_completed_read_without_answer_reports_failed_reply_not_success(client, semantic_provider):
    semantic_provider([{"reads": [{"kind": "recommend"}]},
                       {"reads": [{"kind": "recommend"}]}])
    sid = create_session(client)
    result = send(client, sid, "推荐一下")
    assert result["plan_effect"] == "keep"
    assert any(r.get("code") == "NO_REPLY" and r["status"] == "failed" for r in result["action_results"])
    assert not any(r.get("saved") for r in result["action_results"])


def confirm_current(client, sid):
    current = snapshot(client, sid)
    plan = current["plan"]
    response = client.post(f"/api/v1/guide/tasks/{current['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
            "expected_state_version": current["state_version"],
            "expected_session_version": current["session_version"],
            "selected_items": [{"sku_id": i["sku_id"], "quantity": i["quantity"]}
                               for i in plan["items"] if i.get("selected", True)]})
    assert response.status_code == 200, response.text
    return snapshot(client, sid)


def test_confirm_closes_old_questions_but_post_confirm_chat_can_ask_new_ones(client, semantic_provider):
    semantic_provider(
        [named_purchase(),
         {**question(), "reply": "另一个口味你想要哪一种？"},
         {**question(), "reply": "下次你想买哪一种？"},
         reply_only("可以，先保留这个问题。")]
    )
    sid = create_session(client)
    first = send(client, sid, "先买一件")
    asked = send(client, sid, "另一个口味再问我", first)
    old_id = asked["pending_clarifications"][0]["question_id"]
    confirmed = confirm_current(client, sid)
    assert confirmed["pending_clarifications"] == []
    assert confirmed["plan_read_only"] is True
    next_question = send(client, sid, "下次买哪一种？", confirmed)
    pending = next_question["pending_clarifications"]
    assert pending and pending[0]["question_id"] != old_id
    assert snapshot(client, sid)["pending_clarifications"] == pending
    send(client, sid, "等会再决定", snapshot(client, sid))
    assert snapshot(client, sid)["pending_clarifications"] == pending


def test_new_task_drops_previous_task_pending_and_displayed_candidates(client, semantic_provider):
    def shown_question(request):
        return {**question(), "reply": "这两种你想选哪一个？"}
    provider = semantic_provider(
        [named_purchase(),
         shown_question,
         named_purchase(),
         reply_only("好")]
    )
    sid = create_session(client)
    send(client, sid, "买一件")
    confirmed = confirm_current(client, sid)
    send(client, sid, "下次这两种怎么选？", confirmed)
    assert snapshot(client, sid)["pending_clarifications"]
    new = send(client, sid, "另外新买一件", snapshot(client, sid))
    assert new["task_id"] != confirmed["task_id"]
    assert any(r.get("status") == "committed" for r in new["action_results"])
    restored = snapshot(client, sid)
    assert restored["task_id"] == new["task_id"]
    assert not restored["pending_clarifications"], (new["pending_clarifications"], restored["pending_clarifications"])
    assert not new["pending_clarifications"]
    send(client, sid, "知道了", snapshot(client, sid))
    assert provider.requests[-1]["pending_clarifications"] == []
    assert provider.requests[-1]["displayed_candidates"] == []


def test_product_group_quantity_compiles_to_its_one_item(client, semantic_provider):
    def change(op, quantity):
        def propose(request):
            group = request["current_plan"]["groups"][0]
            return request_amend(focus=group["ref"], name=group["name"], op=op, quantity=quantity)
        return propose
    semantic_provider(
        [named_purchase(),
         named_purchase("可乐", relation="append"),
         change("set_quantity", 2), change("adjust_quantity", -1)]
    )
    sid = create_session(client)
    first = send(client, sid, "买一件")
    both = send(client, sid, "另一件也要", first)
    sku = first["plan"]["items"][0]["sku_id"]
    others = [r for r in both["plan"]["items"] if r["sku_id"] != sku]
    for text, quantity in [("第一件改成两件", 2), ("第一件少一件", 1)]:
        changed = send(client, sid, text, snapshot(client, sid))
        assert changed["plan_effect"] == "replace", changed
        assert next(i for i in changed["plan"]["items"] if i["sku_id"] == sku)["quantity"] == quantity
        assert [r for r in changed["plan"]["items"] if r["sku_id"] != sku] == others


@pytest.mark.parametrize("kind", ["dish", "scenario"])
def test_nonproduct_group_cannot_be_silently_compiled_to_quantity(kind):
    from types import SimpleNamespace
    from app.agent.protocol import CandidateRef, SemanticProtocolError
    from app.agent.tools.change_plan import PlanChangeExecutor
    group = CandidateRef(ref="g", kind="group", target_id="a", name="group", group_id=f"{kind}:a", target_kind=kind)
    state = SimpleNamespace(plan={"items": [{"sku_id": "sku", "group_id": group.group_id}]})
    with pytest.raises(SemanticProtocolError) as error:
        PlanChangeExecutor._group_as_item(state, group)
    assert error.value.code == "UNSUPPORTED_OPERATION"

"""The three everyday shopping lines, end to end through the real services.

These are chain and business checks, not model-quality claims: the model is
scripted, the store, the plan, the pending questions and the cart are real.

* **A — recommend then choose.** The shopper asks for ideas, is shown real
  dishes, and then names one that was never in the shortlist. It has to be
  looked up for real, turned into a confirmable ingredient/goods list, and a
  later chat must not move the plan.
* **B — hotpot, generic.** A scenario is prepared straight from its own
  components/common_tags with no style question; adding a drink afterwards keeps
  what was already there and never touches the cart.
* **C — vague request.** One useful question per turn, carried by the session's
  own pending state, and the shopper stays free to change direction instead of
  being locked into the options they were shown.

Cart writes still use the same confirmation core: either the explicit button
or an explicit chat ``plan_act=confirm`` may call it after the server checks
the current plan and version. Planning, edits, reads and ordinary acknowledgments
do not write the cart.
"""

from __future__ import annotations

import uuid

from support import create_session, post_turn
from support.semantic_agent import (
    continued,
    lookup_then_add,
    pick,
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


def cart_items(client):
    return client.get("/api/v1/cart").json()["items"]


def confirm_current(client, sid):
    """The product's own confirmation endpoint — the only path that writes a cart."""
    current = snapshot(client, sid)
    plan = current["plan"]
    response = client.post(
        f"/api/v1/guide/tasks/{current['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": current["state_version"],
            "expected_session_version": current["session_version"],
            "selected_items": [
                {"sku_id": i["sku_id"], "quantity": i["quantity"]}
                for i in plan["items"]
                if i.get("selected", True)
            ],
        },
    )
    assert response.status_code == 200, response.text
    return snapshot(client, sid)


# ===================================================================== A


def test_a_recommend_dishes_then_choose_one_that_was_not_offered(client, semantic_provider):
    """想吃家常菜 → 真实查两道菜 → 用户点名第三道 → 待确认食材清单。"""
    offered: list[str] = []

    def show_the_real_dishes(request):
        """Everything shown here is a row the retrieval returned, nothing else."""
        results = [r for r in request["query_results"] if r.get("kind") == "lookup"]
        rows = [match for r in results for match in r.get("matches") or []]
        names = [row["name"] for row in rows]
        offered.extend(names)
        return {
            "reply": "这两道都不辣：" + "、".join(names) + "。",
            "display_refs": [row["ref"] for row in rows],
        }

    provider = semantic_provider(
        [
            # 1. two real lookups in the turn's single read round, then the answer
            {
                "target": {"kind": "meal", "intent": "explore"},
                "lookups": [
                    {"kind": "dish", "query": "蒜蓉西兰花"},
                    {"kind": "dish", "query": "蛋炒饭"},
                ],
            },
            continued(show_the_real_dishes),
            # 2. the shopper names a dish not offered; one pass looks it up and
            # binds the exact hit the lookup returns (rule 1).
            *lookup_then_add("dish", "番茄炒蛋", people=2),
            # 3. ordinary chat afterwards
            reply_only("这份清单可以随时改。"),
        ]
    )
    sid = create_session(client)
    cart_before = cart_items(client)

    first = send(client, sid, "想吃点家常菜，不太辣")
    assert first["plan_effect"] == "keep"
    assert first["plan"] is None
    assert first["task_id"] is None
    assert offered, offered
    # Two real dishes from the store, and not the one the shopper later picks.
    assert len(set(offered)) == 2, offered
    assert any("西兰花" in name for name in offered), offered
    assert any("炒饭" in name for name in offered), offered
    assert not any("番茄" in name for name in offered), offered
    # The model was told the real rows, and the answer shows their order.
    lookup_results = [r for r in provider.requests[1]["query_results"]
                      if r.get("kind") == "lookup"]
    assert len(lookup_results) == 2
    assert all(r["status"] == "completed" and r["matches"] for r in lookup_results)
    assert cart_items(client) == cart_before

    second = send(client, sid, "那就番茄炒蛋吧，2人", first)
    assert second["plan_effect"] == "replace"
    assert second["plan"] and second["plan"]["items"]
    targets = {t["name"] for t in second["plan"]["targets"]}
    assert any("番茄" in name for name in targets), targets
    # The list is the dish's real ingredients, turned into real goods.
    item_names = [str(i.get("name") or "") for i in second["plan"]["items"]]
    assert len(item_names) >= 2, item_names
    assert any("番茄" in n or "Tomato" in n for n in item_names), item_names
    assert any("鸡蛋" in n or "Egg" in n for n in item_names), item_names
    # It is a confirmable list, not a cart.
    assert cart_items(client) == cart_before
    assert second["plan"]["can_confirm"] in (True, None)

    plan_version = second["plan"]["plan_version"]
    quantities = [i["quantity"] for i in second["plan"]["items"]]
    third = send(client, sid, "这个清单里有几样东西？", second)
    assert third["plan_effect"] == "keep"
    assert third["plan"] is None
    assert snapshot(client, sid)["plan"]["plan_version"] == plan_version
    assert [i["quantity"] for i in snapshot(client, sid)["plan"]["items"]] == quantities

    # Only the product's own confirmation writes the cart.
    confirmed = confirm_current(client, sid)
    assert confirmed["plan_read_only"] is True
    assert cart_items(client) != cart_before


# ===================================================================== B


def add_scenario(*, people: int = 4):
    """Add the generic hotpot scenario."""

    def build(request):
        scenario = request["candidates"]["scenarios"][0]
        return pick("scenario", scenario, people=people)

    return build


def test_b_hotpot_builds_a_generic_basket(client, semantic_provider):
    """火锅 → 直接生成通用商品清单（不再追问风格），且不碰购物车。"""
    provider = semantic_provider([add_scenario(), reply_only("清单已经更新。")])
    sid = create_session(client)
    cart_before = cart_items(client)

    built = send(client, sid, "晚上想吃火锅，4人")
    assert built["pending_clarifications"] == []
    assert built["plan_effect"] == "replace"
    names = {t["name"] for t in built["plan"]["targets"]}
    assert any("火锅" in name for name in names), names
    assert len(built["plan"]["items"]) > 1  # a real goods list, not one row
    assert cart_items(client) == cart_before  # planning is not buying


def revise_plan(client, sid, *, quantity=None, deselect=None):
    """The plan editor's own endpoint — a user control, not a model turn."""
    current = snapshot(client, sid)
    plan = current["plan"]
    items = []
    for item in plan["items"]:
        row = {
            "sku_id": item["sku_id"],
            # A deselected row is still sent with its real quantity: selection is
            # the shopper's own flag, never a deletion.
            "quantity": (
                quantity[1] if quantity and item["sku_id"] == quantity[0] else item["quantity"]
            ),
            "selected": item.get("selected", True),
        }
        if deselect and item["sku_id"] == deselect:
            row["selected"] = False
        items.append(row)
    response = client.post(
        f"/api/v1/guide/tasks/{current['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": current["session_version"],
            "expected_state_version": current["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "items": items,
        },
    )
    assert response.status_code == 200, response.text
    return snapshot(client, sid)


def test_b_a_manual_edit_survives_a_later_add(client, semantic_provider):
    """用清单编辑器改数量/取消勾选，再追加商品：用户改动不被重建。"""
    provider = semantic_provider(
        [
            add_scenario(),
            *lookup_then_add("product", "可乐 330毫升", relation="append"),
        ]
    )
    sid = create_session(client)
    built = send(client, sid, "晚上想吃火锅，4人")
    assert len(built["plan"]["items"]) >= 2, built["plan"]["items"]

    edited_sku = built["plan"]["items"][0]["sku_id"]
    untouched_sku = built["plan"]["items"][1]["sku_id"]
    target = built["plan"]["items"][0]["quantity"] + 1

    # The shopper edits through the plan editor: one row up, one row un-ticked.
    edited = revise_plan(client, sid, quantity=(edited_sku, target), deselect=untouched_sku)
    rows = {i["sku_id"]: i for i in edited["plan"]["items"]}
    assert rows[edited_sku]["quantity"] == target
    assert rows[edited_sku]["quantity_source"] == "user"
    assert rows[untouched_sku]["selected"] is False

    # A later add must not rebuild the row the shopper set by hand.
    added = send(client, sid, "再来一瓶可乐", snapshot(client, sid))
    assert added["plan_effect"] == "replace"
    after = {i["sku_id"]: i for i in added["plan"]["items"]}
    assert after[edited_sku]["quantity"] == target
    assert after[edited_sku]["quantity_source"] == "user"
    # ...and the drink really was added.
    assert set(after) > set(rows)
    # KNOWN, REPORTED, NOT FIXED HERE: an append re-derives ``selected`` from the
    # merged contributions, so a row the shopper un-ticked comes back ticked.
    # That is ``ShoppingPlanService.merge_plan`` behaviour (business rule, outside
    # this batch's boundary), not something this test should pin as correct.


# ===================================================================== C


#: One useful question, asked in the understanding pass itself: a question is
#: never raised after retrieval (the answer stage only puts results into words).
ASK_DIRECTION = {
    "reply": "先问一句：今晚想清淡一点还是下饭一点？",
    "questions": [{"slot": "direction", "question": "今晚想清淡一点还是下饭一点？"}],
}


def name_a_dish_instead(request):
    """Name a dish outside the question, and say which open question it answers."""
    (build,) = lookup_then_add("dish", "番茄炒蛋", people=2)
    answered = [q["question_id"] for q in request.get("pending_clarifications") or []]
    return {**build(request), "resolved_questions": answered}


def test_c_a_vague_request_asks_one_question_and_stays_open(client, semantic_provider):
    """模糊需求 → 每轮一个问题 → pending 承接 → 用户可改方向。"""
    provider = semantic_provider(
        [
            # 1. vague: ask exactly one useful question
            ASK_DIRECTION,
            # 2. the shopper changes direction and names a dish; one pass looks
            # it up, binds the exact hit (rule 1) and closes the open question.
            name_a_dish_instead,
            reply_only("好，就照这份清单来。"),
        ]
    )
    sid = create_session(client)

    first = send(client, sid, "随便推荐点吧")
    assert first["plan_effect"] == "keep"
    assert first["plan"] is None
    assert len(first["pending_clarifications"]) == 1
    asked = first["pending_clarifications"][0]
    assert asked["slot"] == "direction"

    # The next turn really carries the open question forward.
    second = send(client, sid, "我想吃番茄炒蛋，2人", first)
    assert second["plan_effect"] == "replace"
    assert second["plan"] and second["plan"]["items"]
    targets = {t["name"] for t in second["plan"]["targets"]}
    # The shopper was not locked into the two options they were shown.
    assert any("番茄" in name for name in targets), targets
    assert not second["pending_clarifications"]
    assert snapshot(client, sid)["pending_clarifications"] == []


def test_c_the_pending_question_is_carried_into_the_next_request(client, semantic_provider):
    """The model is told what it asked; the session owns that, not the prose."""
    provider = semantic_provider([ASK_DIRECTION, reply_only("不急，想好了再说。")])
    sid = create_session(client)
    first = send(client, sid, "随便推荐点吧")
    send(client, sid, "等一下", first)

    carried = provider.requests[-1]
    assert carried["pending_clarifications"] == first["pending_clarifications"]
    assert carried["pending_clarification"]["slot"] == "direction"


# ====================================================== candidate-set regressions


def test_the_stand_in_switches_only_on_a_named_replacement(client, reactive_agent):
    """Positive/negative protection for the shared stand-in's switch reading.

    A *named* replacement (``换成宫保鸡丁``) means "replace the goal": it must be
    declared as a switch and open its own task. A bare cancellation (``取消``) names
    no new target and must never be turned into one — the turn keeps the task.
    """
    sid = create_session(client)
    first = send(client, sid, "我想吃番茄炒蛋，2人")
    assert first["plan"], first

    cancelled = send(client, sid, "取消", first)
    assert cancelled["task_id"] == first["task_id"], cancelled
    assert cancelled["plan_effect"] == "keep", cancelled

    switched = send(client, sid, "换成宫保鸡丁", cancelled)
    assert switched["plan"], switched
    assert switched["task_id"] != first["task_id"], switched
    names = " ".join(i.get("name") or "" for i in switched["plan"]["items"])
    assert "花生" in names or "鸡胸" in names or "鸡腿" in names, names


def test_no_product_or_dish_is_offered_before_it_was_retrieved(client, semantic_provider):
    """Nothing becomes referenceable just because it sorts first in a table."""
    from app.agent import context as turn_context

    sid = create_session(client)
    candidates = turn_context.build_candidate_set(
        None, store_id="store-demo-01", delivery_zone_id="zone-default", state=None
    )
    assert candidates.by_kind("product") == []
    assert candidates.by_kind("dish") == []
    assert candidates.by_kind("item") == []
    assert candidates.by_kind("group") == []
    # Scenario metadata stays: it is a small closed fixture with no prices, and
    # the server offers the open scenario as a real target.
    assert candidates.by_kind("scenario")

    seen: list[list[dict]] = []

    def look(request):
        seen.append(list(request["candidates"]["products"]))
        return {"reads": [{"kind": "recommend", "topic": "可乐"}]}

    provider = semantic_provider([look, reply_only("好。")])
    send(client, sid, "有可乐吗")
    assert seen[0] == []  # the first request offers no product at all
    assert provider.requests[0]["candidates"]["products"] == []

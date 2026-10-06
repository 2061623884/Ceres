"""Phase 2e meal fulfilment feedback through the real SSE and persistence path."""

import json
from pathlib import Path

import pytest

from app.agent.tools.read import ReadTools
from support import create_session, post_turn
from support.semantic_agent import Continuation, request_amend, request_new
from test_semantic_phase1_purchase import indexed_client


PREPARED_SKU = "phase2e:tomato-egg-ready-meal"
TAGGED_INGREDIENT_SKU = "phase2e:egg-with-meal-usage-tag"


def _publish_temp_index(client, test_db_url, monkeypatch, tmp_path, name):
    from app.core.config import get_settings
    from app.services.retrieval_index import publish, write_index
    from app.services.retrieval_projection import build_projection

    database = Path(test_db_url.removeprefix("sqlite:///"))
    projection, dictionary = build_projection(database)
    index_root = tmp_path / "index"
    write_index(
        target_dir=index_root / name,
        projection=projection,
        dictionary=dictionary,
        embedding=None,
        vectors=None,
    )
    publish(index_root, name)
    monkeypatch.setenv("RETRIEVAL_INDEX_DIR", str(index_root))
    monkeypatch.setenv("RETRIEVAL_MODE", "lexical")
    get_settings.cache_clear()
    return client


@pytest.fixture()
def prepared_meal_client(client, test_db_url, monkeypatch, tmp_path):
    from app.core.database import SessionLocal
    from app.models.catalog import CatalogProduct
    from app.models.store import Offer

    with SessionLocal() as db:
        db.add(CatalogProduct(
            sku_id=PREPARED_SKU,
            name="番茄炒蛋即食餐",
            name_zh="番茄炒蛋即食餐",
            category_id="demo",
            ingredient_ids="[]",
            usage_tags="[]",
            source="phase2e-test",
            review_status="approved",
        ))
        db.add(Offer(
            store_id="store-demo-01",
            sku_id=PREPARED_SKU,
            price_fen=2680,
            available_qty=20,
            sellable=True,
        ))
        db.commit()

    return _publish_temp_index(
        client, test_db_url, monkeypatch, tmp_path, "prepared-meal"
    )


@pytest.fixture()
def tagged_ingredient_client(client, test_db_url, monkeypatch, tmp_path):
    from app.core.database import SessionLocal
    from app.models.catalog import CatalogProduct
    from app.models.store import Offer

    with SessionLocal() as db:
        db.add(CatalogProduct(
            sku_id=TAGGED_INGREDIENT_SKU,
            name="Eggs 10 pack",
            name_zh="鸡蛋 10枚装",
            category_id="demo",
            ingredient_ids='["egg"]',
            usage_tags='["番茄炒蛋"]',
            source="phase2e-test",
            review_status="approved",
        ))
        db.add(Offer(
            store_id="store-demo-01",
            sku_id=TAGGED_INGREDIENT_SKU,
            price_fen=1290,
            available_qty=20,
            sellable=True,
        ))
        db.commit()

    return _publish_temp_index(
        client, test_db_url, monkeypatch, tmp_path, "tagged-ingredient"
    )


def _send(client, sid, text, previous=None):
    response = post_turn(client, sid, text, previous)
    assert response.status_code == 200, response.json()
    return response.json()


def _named_meal(name, **constraints):
    proposal = request_new("dish", name, constraints=constraints)
    proposal["lookups"] = [{"kind": "dish", "query": name}]
    return proposal


def _patch_group(request, **changes):
    group = request["current_plan"]["groups"][0]
    return request_amend(
        focus=group["ref"],
        name=group["name"],
        changes={"set": changes},
    )


def _saved_task(task_id):
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    with SessionLocal() as db:
        task = db.get(GuideTask, task_id)
        return {
            "state_version": task.state_version,
            "current_step": task.current_step,
            "plan": json.loads(task.plan_json),
            "requirements": json.loads(task.requirements_json),
        }


def _observe_reads(monkeypatch):
    reads = []
    original = ReadTools.serve

    def record(self, proposal, candidates, *, lookup_limit):
        results = original(self, proposal, candidates, lookup_limit=lookup_limit)
        for result in results:
            matches = result.get("matches") or []
            reads.append({
                **result,
                "candidate_ids": {
                    match["ref"]: candidates.resolve(match["ref"]).target_id
                    for match in matches
                },
            })
        return results

    monkeypatch.setattr(ReadTools, "serve", record)
    return reads


def test_named_meal_self_cook_is_metadata_only_and_same_constraints_are_noops(
    indexed_client, semantic_provider
):
    semantic_provider([
        _named_meal(
            "番茄炒蛋", budget_yuan=100, excluded_ingredients=["鸡肉"]
        ),
        lambda request: _patch_group(request, fulfillment_mode="self_cook"),
        lambda request: _patch_group(request, fulfillment_mode="self_cook"),
        lambda request: _patch_group(
            request,
            fulfillment_mode="self_cook",
            budget_yuan=100,
            excluded_ingredients=["鸡肉"],
        ),
        {"reads": [{"kind": "cart"}]},
        Continuation(lambda _request: {"reply": "购物车目前没有商品。", "display_refs": []}),
    ])
    sid = create_session(indexed_client)
    first = _send(indexed_client, sid, "我要番茄炒蛋，预算100，不要鸡肉")
    first_plan = first["plan"]

    changed = _send(indexed_client, sid, "自己做", first)
    assert changed["plan_effect"] == "replace", changed
    assert changed["plan"]["plan_id"] == first_plan["plan_id"]
    assert changed["plan"]["plan_version"] == first_plan["plan_version"]
    assert changed["plan"]["items"] == first_plan["items"]
    assert changed["plan"]["targets"][0]["meal_name"] == "番茄炒蛋"
    assert changed["plan"]["targets"][0]["fulfillment_mode"] == "self_cook"
    saved_after_change = _saved_task(first["task_id"])
    assert saved_after_change["state_version"] == first["state_version"] + 1
    assert saved_after_change["plan"]["targets"][0]["meal_name"] == "番茄炒蛋"
    assert saved_after_change["plan"]["targets"][0]["fulfillment_mode"] == "self_cook"

    repeated_mode = _send(indexed_client, sid, "还是自己做", changed)
    repeated_constraints = _send(
        indexed_client, sid, "预算100，不要鸡肉", repeated_mode
    )
    for no_op in (repeated_mode, repeated_constraints):
        assert no_op["plan_effect"] == "keep", no_op
        assert no_op["plan"] is None
        assert no_op["state_version"] == changed["state_version"]
        assert no_op["status"] == no_op["answer_status"] == "awaiting_confirmation", no_op
        assert no_op["message"].strip(), no_op
        assert not any(
            result.get("code") in {"UNSUPPORTED_CHANGE_FIELD", "NO_REPLY", "EMPTY_PROPOSAL"}
            for result in no_op["action_results"]
        )
        assert not any(
            result.get("type") == "understanding_failed"
            for result in no_op["action_results"]
        )
        saved_no_op = _saved_task(first["task_id"])
        assert saved_no_op["plan"] == saved_after_change["plan"]
        assert saved_no_op["state_version"] == saved_after_change["state_version"]

    read_only = _send(indexed_client, sid, "购物车有什么？", repeated_constraints)
    assert read_only["plan_effect"] == "keep"
    assert read_only["plan"] is None
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    saved_final = _saved_task(first["task_id"])
    assert saved_final["plan"] == saved_after_change["plan"]
    assert saved_final["state_version"] == saved_after_change["state_version"]


def test_system_selected_meal_keeps_same_constraints_and_inherits_mode_on_switch(
    indexed_client, semantic_provider, monkeypatch
):
    reads = _observe_reads(monkeypatch)

    def switch(request):
        return request_new("dish", "", relation="switch")

    semantic_provider([
        request_new(
            "dish", "", constraints={
                "budget_yuan": 50,
                "excluded_ingredients": ["鸡蛋"],
            }
        ),
        lambda request: _patch_group(request, fulfillment_mode="self_cook"),
        lambda request: _patch_group(
            request,
            fulfillment_mode="self_cook",
            budget_yuan=50,
            excluded_ingredients=["鸡蛋"],
        ),
        switch,
    ])
    sid = create_session(indexed_client)
    first = _send(indexed_client, sid, "预算50，不要鸡蛋，你帮我配一餐")
    before = first["plan"]
    assert before["targets"][0]["selection_goal"]["constraints"]["budget_yuan"] == 50
    assert before["targets"][0]["selection_goal"]["constraints"]["excluded_ingredients"] == ["鸡蛋"]
    assert len([r for r in reads if r.get("kind") == "recommend"]) == 1

    mode = _send(indexed_client, sid, "自己做", first)
    assert mode["plan_effect"] == "replace", mode
    target = mode["plan"]["targets"][0]
    assert target["selection_goal"]["fulfillment_mode"] == "self_cook"
    assert target["selection_goal"]["constraints"]["budget_yuan"] == 50
    assert target["selection_goal"]["constraints"]["excluded_ingredients"] == ["鸡蛋"]
    assert mode["plan"]["items"] == before["items"]
    assert mode["plan"]["plan_id"] == before["plan_id"]
    assert mode["plan"]["plan_version"] == before["plan_version"]
    assert len([r for r in reads if r.get("kind") == "recommend"]) == 1

    same = _send(indexed_client, sid, "预算50，不要鸡蛋，还是自己做", mode)
    assert same["plan_effect"] == "keep", same
    assert same["plan"] is None
    assert same["task_id"] == mode["task_id"]
    assert same["state_version"] == mode["state_version"]
    assert same["status"] == same["answer_status"] == "awaiting_confirmation", same
    assert same["message"].strip(), same
    assert not any(
        result.get("code") in {"UNSUPPORTED_CHANGE_FIELD", "NO_REPLY", "EMPTY_PROPOSAL"}
        for result in same["action_results"]
    )
    assert not any(
        result.get("type") == "understanding_failed"
        for result in same["action_results"]
    )
    assert len([r for r in reads if r.get("kind") == "recommend"]) == 1

    switched = _send(indexed_client, sid, "换一个", same)
    assert switched["plan_effect"] == "replace", switched
    after = switched["plan"]["targets"][0]
    assert after["selection_goal"]["fulfillment_mode"] == "self_cook"
    assert after["selection_goal"]["constraints"]["budget_yuan"] == 50
    assert after["selection_goal"]["constraints"]["excluded_ingredients"] == ["鸡蛋"]
    assert switched["plan"]["targets"][0]["target_id"] != before["targets"][0]["target_id"]
    assert switched["plan"]["selected_total_fen"] <= 5000
    assert all("鸡蛋" not in item["name"] for item in switched["plan"]["items"])
    assert len([r for r in reads if r.get("kind") == "recommend"]) == 2
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_ready_made_and_self_cook_switch_use_real_read_refs_for_the_same_meal(
    prepared_meal_client, semantic_provider, monkeypatch
):
    reads = _observe_reads(monkeypatch)
    semantic_provider([
        _named_meal("番茄炒蛋"),
        lambda request: _patch_group(request, fulfillment_mode="ready_made"),
        lambda request: _patch_group(request, fulfillment_mode="self_cook"),
    ])
    sid = create_session(prepared_meal_client)
    first = _send(prepared_meal_client, sid, "我要番茄炒蛋")
    ready = _send(prepared_meal_client, sid, "要现成的", first)

    assert ready["plan_effect"] == "replace", {
        "route": ready.get("route"),
        "status": ready.get("status"),
        "message": ready.get("message"),
        "action_results": ready.get("action_results"),
        "plan": ready.get("plan"),
    }
    ready_target = ready["plan"]["targets"][0]
    assert ready_target["kind"] == "product"
    assert ready_target["target_id"] == PREPARED_SKU
    assert ready_target["meal_name"] == "番茄炒蛋"
    assert ready_target["fulfillment_mode"] == "ready_made"
    product_reads = [
        result for result in reads
        if result.get("kind") == "lookup" and result.get("lookup_kind") == "product"
    ]
    assert any(
        match.get("target_id") == PREPARED_SKU
        and result["candidate_ids"][match["ref"]] == PREPARED_SKU
        for result in product_reads
        for match in result.get("matches", [])
    ), product_reads
    assert [item["sku_id"] for item in ready["plan"]["items"]] == [PREPARED_SKU]

    cooked = _send(prepared_meal_client, sid, "自己做", ready)
    assert cooked["plan_effect"] == "replace", cooked
    cooked_target = cooked["plan"]["targets"][0]
    assert cooked_target["kind"] == "dish"
    assert cooked_target["target_id"] == "dish-fanqie-chao-dan"
    assert cooked_target["meal_name"] == "番茄炒蛋"
    assert cooked_target["fulfillment_mode"] == "self_cook"
    assert PREPARED_SKU not in {item["sku_id"] for item in cooked["plan"]["items"]}
    assert prepared_meal_client.get("/api/v1/cart").json()["items"] == []


def test_usage_tagged_ingredient_is_not_accepted_as_a_ready_made_meal(
    tagged_ingredient_client, semantic_provider, monkeypatch
):
    reads = _observe_reads(monkeypatch)
    semantic_provider([
        _named_meal("番茄炒蛋"),
        lambda request: _patch_group(request, fulfillment_mode="ready_made"),
    ])
    sid = create_session(tagged_ingredient_client)
    first = _send(tagged_ingredient_client, sid, "我要番茄炒蛋")
    task_before = _saved_task(first["task_id"])
    old_plan = task_before["plan"]
    cart_before = tagged_ingredient_client.get("/api/v1/cart").json()["items"]

    refused = _send(tagged_ingredient_client, sid, "要现成的", first)
    assert refused["plan_effect"] == "keep", refused
    assert refused["plan"] is None
    assert refused["task_id"] == first["task_id"]
    assert refused["state_version"] == first["state_version"]
    assert refused["committed"] is False
    assert any(
        result.get("code") == "GOAL_TARGET_UNRESOLVED"
        for result in refused["action_results"]
    ), refused["action_results"]
    assert not any(
        result.get("saved") is True or result.get("status") == "committed"
        for result in refused["action_results"]
    ), refused["action_results"]
    assert "没有找到" in refused["message"] and "成品商品" in refused["message"], refused
    assert _saved_task(first["task_id"]) == task_before
    assert any(
        result.get("kind") == "lookup"
        and result.get("lookup_kind") == "product"
        and TAGGED_INGREDIENT_SKU in result.get("candidate_ids", {}).values()
        for result in reads
    ), reads
    assert TAGGED_INGREDIENT_SKU not in {item["sku_id"] for item in old_plan["items"]}
    assert tagged_ingredient_client.get("/api/v1/cart").json()["items"] == cart_before


def test_mode_switch_refuses_a_multi_group_plan_without_dropping_either_group(
    indexed_client, semantic_provider
):
    semantic_provider([
        _named_meal("番茄炒蛋"),
        {**request_new("dish", "宫保鸡丁", relation="append"),
         "lookups": [{"kind": "dish", "query": "宫保鸡丁"}]},
        lambda request: request_amend(
            focus=request["current_plan"]["groups"][0]["ref"],
            name=request["current_plan"]["groups"][0]["name"],
            changes={"set": {"fulfillment_mode": "ready_made"}},
        ),
    ])
    sid = create_session(indexed_client)
    first = _send(indexed_client, sid, "我要番茄炒蛋")
    second = _send(indexed_client, sid, "再加宫保鸡丁", first)
    before = _saved_task(second["task_id"])
    assert {target["meal_name"] for target in second["plan"]["targets"]} == {
        "番茄炒蛋", "宫保鸡丁",
    }

    refused = _send(indexed_client, sid, "第一道要现成的", second)
    assert refused["plan_effect"] == "keep", refused
    assert refused["plan"] is None
    assert refused["task_id"] == second["task_id"]
    after = _saved_task(second["task_id"])
    assert after["plan"] == before["plan"]
    assert after["state_version"] == before["state_version"]
    assert {target["meal_name"] for target in after["plan"]["targets"]} == {
        "番茄炒蛋", "宫保鸡丁",
    }
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_fulfillment_feedback_on_a_confirmed_task_keeps_history_and_cart(
    indexed_client, semantic_provider
):
    semantic_provider([
        _named_meal("番茄炒蛋"),
        lambda request: _patch_group(request, fulfillment_mode="self_cook"),
    ])
    sid = create_session(indexed_client)
    first = _send(indexed_client, sid, "我要番茄炒蛋")
    plan = first["plan"]
    selected_items = [
        {"sku_id": item["sku_id"], "quantity": item["quantity"]}
        for item in plan["items"]
        if item.get("selected", True) and item.get("role", "required") == "required"
    ]
    confirmed = indexed_client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": "phase2e-terminal-feedback"},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": first["state_version"],
            "expected_session_version": first["session_version"],
            "selected_items": selected_items,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    cart_before = indexed_client.get("/api/v1/cart").json()["items"]
    after_confirm = indexed_client.get(
        f"/api/v1/guide/sessions/{sid}"
    ).json()
    task_before = _saved_task(first["task_id"])

    refused = _send(indexed_client, sid, "自己做", after_confirm)
    assert refused["plan_effect"] == "keep", refused
    assert refused["plan"] is None
    assert refused["task_id"] == first["task_id"]
    assert _saved_task(first["task_id"]) == task_before
    assert indexed_client.get("/api/v1/cart").json()["items"] == cart_before

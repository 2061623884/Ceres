"""O00 red regression tests for F01/F03/F04/F06."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.evaluation.runner import EvalConfigError, load_cases, main, validate_case_config
from app.schemas.guide import ConfirmItem
from support import post_turn


def _session(client, **ctx):
    entry = {
        "page": "home",
        "category_id": None,
        "store_id": "store-demo-01",
        "delivery_zone_id": "zone-default",
        **ctx,
    }
    return client.post("/api/v1/guide/sessions", json={"entry_context": entry}).json()["session_id"]


def _turn(client, sid, message, task_id=None, version=0):
    return post_turn(client, sid, message, None, request_id=str(uuid.uuid4()))


def _confirm(client, task_id, plan, state_version, idem_key="confirm-key-1"):
    if plan.get("mode") == "alternatives":
        first = plan["items"][0]
        items = [{"sku_id": first["sku_id"], "quantity": first["quantity"]}]
    else:
        items = [
            {"sku_id": i["sku_id"], "quantity": i["quantity"]}
            for i in plan["items"]
            if i.get("selected", i.get("role", "required") != "pantry")
        ]
    return client.post(
        f"/api/v1/guide/tasks/{task_id}/confirm",
        headers={"Idempotency-Key": idem_key},
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": state_version,
            "selected_items": items,
        },
    )


def test_f01_confirm_after_tomato_egg_not_500(client):
    """F01: confirm must not return HTTP 500 after template plan."""
    sid = _session(client)
    turn = _turn(client, sid, "我想吃番茄炒蛋")
    assert turn.status_code == 200
    body = turn.json()
    assert body["status"] == "awaiting_confirmation"
    plan = body["plan"]
    confirm = _confirm(client, body["task_id"], plan, body["state_version"])
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "completed"


def test_f01_confirm_after_baking_category_not_500(client):
    sid = _session(client, page="category", category_id="baking")
    turn = _turn(client, sid, "想做蛋糕，面粉小包装，20元以内")
    assert turn.status_code == 200
    body = turn.json()
    if body["status"] == "awaiting_confirmation" and body.get("plan"):
        confirm = _confirm(client, body["task_id"], body["plan"], body["state_version"], "bake-confirm")
        assert confirm.status_code == 200, confirm.text


def test_f03_fuzzy_dinner_no_whole_sentence_keyword(client):
    """F03: after people+budget, search must not use the full user sentence as keyword."""
    sid = _session(client)
    r1 = _turn(client, sid, "今晚想做顿简单的饭")
    task_id = r1.json()["task_id"]
    version = r1.json()["state_version"]
    r2 = _turn(client, sid, "两个人，清淡一点，预算五十元以内", task_id, version)
    assert r2.status_code == 200
    body = r2.json()
    if body.get("plan"):
        for item in body["plan"]["items"]:
            name = item.get("name") or ""
            assert "今晚想做顿简单的饭" not in name


def test_f03_baking_flour_excludes_baking_powder(client):
    sid = _session(client, page="category", category_id="baking")
    turn = _turn(client, sid, "蛋糕面粉，小包装")
    assert turn.status_code == 200
    body = turn.json()
    if body.get("plan"):
        sku_ids = {i["sku_id"] for i in body["plan"]["items"]}
        assert "demo:baking-powder-100g" not in sku_ids
        names = " ".join(i.get("name") or "" for i in body["plan"]["items"])
        assert "泡打粉" not in names


def test_f04_patch_qty_exceeds_stock_returns_422(client):
    products = client.get("/api/v1/products", params={"category_id": "baking"}).json()["items"]
    sku = next(p["sku_id"] for p in products if p["sku_id"] == "demo:cake-flour-250g")
    add = client.post(
        "/api/v1/cart/items",
        json={"sku_id": sku, "quantity": 1, "expected_cart_version": 0},
    )
    assert add.status_code == 200
    version = add.json()["version"]
    patch = client.patch(
        f"/api/v1/cart/items/{sku}",
        json={"quantity": 99, "expected_cart_version": version},
    )
    assert patch.status_code == 422


def test_f04_unknown_delivery_zone_not_reachable(client):
    from app.services.delivery_service import DeliveryService
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        assert DeliveryService(db).check_delivery("store-demo-01", "zone-unknown") is False
    finally:
        db.close()


def test_f04_negative_qty_schema_rejected():
    with pytest.raises(ValidationError):
        ConfirmItem(sku_id="demo:x", quantity=-3)


def test_f06_eval_rejects_empty_dataset(tmp_path, monkeypatch):
    import app.evaluation.runner as runner_mod

    empty_dir = tmp_path / "evals" / "v1"
    empty_dir.mkdir(parents=True)
    monkeypatch.setattr(runner_mod, "ROOT", tmp_path)
    assert load_cases() == []
    # Exercise the empty-dataset guard through the supported CLI, never a model.
    monkeypatch.setattr("sys.argv", ["runner", "--mode", "live"])
    monkeypatch.setattr(
        "app.llm.provider.get_semantic_provider",
        lambda: pytest.fail("An empty dataset must not request a model"),
    )
    assert main() != 0


def test_f06_eval_rejects_empty_expected_actions():
    with pytest.raises(EvalConfigError, match="empty expected_actions"):
        validate_case_config({"case_id": "x", "turns": [{"message": "hi"}], "expected_actions": []})


def test_f06_eval_rejects_unknown_assertion_type():
    with pytest.raises(EvalConfigError, match="unknown action"):
        validate_case_config(
            {"case_id": "x", "turns": [{"message": "hi"}], "expected_actions": ["bogus_action"]}
        )


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

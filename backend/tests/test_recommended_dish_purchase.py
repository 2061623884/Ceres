"""One recommended dish through real supply, revisions, ACK and confirmation."""
import json
import uuid

import pytest

from support import create_session, send_turn
from support.semantic_agent import request_new
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_recommended_dish_reason_and_purchase(indexed_client, semantic_provider, run):
    semantic_provider([
        request_new("dish", "", constraints={"budget_yuan": 30}),
        {"reply": "好的，清单先保留，等你明确确认后再加购。"},
    ])
    client = indexed_client
    sid = create_session(client)
    turn = send_turn(client, sid, "今晚自己做一道菜，预算30元，没有忌口，你帮我推荐一道菜")
    plan = turn["plan"]
    assert len(plan["targets"]) == 1
    assert f"主推「{plan['targets'][0]['name']}」" in turn["message"]
    assert not any(
        line.partition(". ")[0].isdigit()
        for line in turn["message"].splitlines()
    )
    assert "必需食材" in turn["message"] and "预算内" in turn["message"]
    assert f"{plan['selected_total_fen'] / 100:.2f}" in turn["message"]
    assert all(i["selected"] for i in plan["items"] if i["role"] == "required")
    assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
    from app.core.database import SessionLocal
    from app.models.session import GuideSemanticContext

    with SessionLocal() as db:
        context = json.loads(db.get(GuideSemanticContext, sid).context_json)
    assert context.get("displayed_candidates", []) == []
    for item in plan["items"]:
        product = client.get(f"/api/v1/products/{item['sku_id']}").json()
        assert item["unit_price_fen"] == product["price_fen"]
    assert client.get("/api/v1/cart").json()["items"] == []
    pantry = next(i for i in plan["items"] if i["role"] == "pantry")
    response = client.post(f"/api/v1/guide/tasks/{turn['task_id']}/plan-revisions", json={
        "request_id": str(uuid.uuid4()), "expected_session_version": turn["session_version"],
        "expected_state_version": turn["state_version"], "base_plan_id": plan["plan_id"],
        "base_plan_version": plan["plan_version"], "coverage_intent": "partial_ok",
        "items": [{"sku_id": i["sku_id"], "quantity": i["quantity"],
                   "selected": i["selected"] or i["sku_id"] == pantry["sku_id"]} for i in plan["items"]],
    })
    assert response.status_code == 200
    session = client.get(f"/api/v1/guide/sessions/{sid}").json()
    saved_plan = session["plan"]
    turn = send_turn(client, sid, "好的", session)
    restored = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["plan"] == saved_plan
    assert client.get("/api/v1/cart").json()["items"] == []
    result = client.post(f"/api/v1/guide/tasks/{turn['task_id']}/confirm", json={
        "plan_id": saved_plan["plan_id"], "plan_version": saved_plan["plan_version"],
        "expected_session_version": restored["session_version"], "expected_state_version": restored["state_version"],
        "selected_items": [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                           for i in saved_plan["items"] if i["selected"]],
    }, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert result.status_code == 200
    cart = client.get("/api/v1/cart").json()
    assert cart["total_price_fen"] == saved_plan["outstanding_total_fen"]
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        i["sku_id"]: i["remaining_quantity"] for i in saved_plan["items"] if i["selected"]}

"""Public API contract used by the homepage purchase checklist."""

import uuid

import pytest

from support import create_session, send_turn


@pytest.mark.parametrize("run", [1, 2])
def test_selection_revision_restore_and_confirm(client, reactive_agent, run):
    sid = create_session(client)
    turn = send_turn(client, sid, "我想做番茄炒蛋")
    plan = turn["plan"]
    assert all(i["selected"] for i in plan["items"] if i["role"] == "required")
    assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
    assert client.get("/api/v1/cart").json()["items"] == []
    tomato = next(i for i in plan["items"] if "tomato" in i["sku_id"])
    oil = next(i for i in plan["items"] if "oil" in i["sku_id"])
    edits = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"],
         "selected": i["sku_id"] == oil["sku_id"] or
         (i["selected"] and i["sku_id"] != tomato["sku_id"])}
        for i in plan["items"]
    ]
    revision = client.post(
        f"/api/v1/guide/tasks/{turn['task_id']}/plan-revisions",
        json={"request_id": str(uuid.uuid4()),
              "expected_session_version": turn["session_version"],
              "expected_state_version": turn["state_version"],
              "base_plan_id": plan["plan_id"], "base_plan_version": plan["plan_version"],
              "coverage_intent": "partial_ok", "items": edits},
    )
    assert revision.status_code == 200
    revised = revision.json()
    assert revised["plan_version"] == plan["plan_version"] + 1
    assert revised["coverage_mode"] == "partial"
    assert revised["can_confirm"] is True
    chosen = [i for i in revised["items"] if i["selected"]]
    total = sum(i["unit_price_fen"] * i["quantity"] for i in chosen)
    assert total == revised["selected_total_fen"] == revised["outstanding_total_fen"]
    restored = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert restored["plan"]["items"] == revised["items"]
    assert restored["plan"]["total_price_fen"] == total
    assert restored["session_version"] == revised["session_version"]
    assert client.get("/api/v1/cart").json()["items"] == []
    result = client.post(
        f"/api/v1/guide/tasks/{turn['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": revised["plan_id"], "plan_version": revised["plan_version"],
              "expected_session_version": revised["session_version"],
              "expected_state_version": revised["state_version"],
              "selected_items": [{"sku_id": i["sku_id"], "quantity": i["quantity"]} for i in chosen]},
    )
    assert result.status_code == 200
    cart = client.get("/api/v1/cart").json()
    assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {
        i["sku_id"]: i["quantity"] for i in chosen}
    assert cart["total_price_fen"] == total


@pytest.mark.parametrize("run", [1, 2])
def test_empty_selection_remains_revisable_after_restore(client, reactive_agent, run):
    sid = create_session(client)
    turn = send_turn(client, sid, "我想做番茄炒蛋")
    plan = turn["plan"]
    edits = [{"sku_id": i["sku_id"], "quantity": i["quantity"], "selected": False} for i in plan["items"]]
    for selected in (False, True):
        edits[0]["selected"] = selected
        response = client.post(
            f"/api/v1/guide/tasks/{turn['task_id']}/plan-revisions",
            json={"request_id": str(uuid.uuid4()),
                  "expected_session_version": turn["session_version"],
                  "expected_state_version": turn["state_version"],
                  "base_plan_id": plan["plan_id"], "base_plan_version": plan["plan_version"],
                  "coverage_intent": "partial_ok", "items": edits},
        )
        assert response.status_code == 200
        revised = response.json()
        assert revised["can_confirm"] is selected
        turn = client.get(f"/api/v1/guide/sessions/{sid}").json()
        plan = turn["plan"]
        assert plan["plan_version"] == revised["plan_version"]
        assert plan["items"][0]["selected"] is selected
        assert client.get("/api/v1/cart").json()["items"] == []

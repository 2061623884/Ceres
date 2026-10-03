"""Snack category reads, displayed selection and explicit cart confirmation."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.core.config import get_settings
from support import create_session, send_turn
from support.semantic_agent import pick

ROOT = Path(__file__).resolve().parents[2]
CHIPS = "demo:snack-original-potato-chips-70g-bag"
CRACKERS = "demo:snack-soda-crackers-100g-box"


@pytest.mark.parametrize("index,message", [(0, "就第一个"), (1, "就第二个")])
def test_snack_selection_requires_confirmation_and_preserves_cart_on_no_match(
    client, semantic_provider, tmp_path, monkeypatch, index, message
):
    settings = get_settings()
    index_root = tmp_path / "retrieval-index"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_retrieval_index.py"),
         "--index-root", str(index_root), "build", "--candidate-db",
         str(settings.runtime_db_path), "--no-embed"],
        check=True, capture_output=True, text=True,
    )
    monkeypatch.setattr(settings, "retrieval_index_dir", str(index_root))
    shown = []

    def display(request):
        rows = request["candidates"]["products"]
        assert {row["target_id"] for row in request["query_results"][0]["matches"]} == {CHIPS, CRACKERS}
        # Display order differs from lookup order, so an ordinal must use refs.
        shown.extend(reversed(rows))
        return {"reply": "可选这两款零食。", "display_refs": [row["ref"] for row in shown]}

    def select(request):
        displayed = request["displayed_candidates"]
        assert [row["ref"] for row in displayed] == [row["ref"] for row in shown]
        return pick("product", displayed[index], quantity=1)

    def no_match(request):
        assert request["query_results"][0]["matches"] == []
        assert request["query_results"][0]["status"] == "completed"
        assert request["query_results"][0]["empty"] is True
        return {"reply": "没有找到匹配的冰淇淋商品。", "display_refs": []}

    provider = semantic_provider([
        {"target": {"kind": "category", "name": "零食", "intent": "explore"},
         "lookups": [{"kind": "product", "query": "零食"}]},
        display, select, {"plan_act": "none", "reply": "清单已准备好，等待确认。"},
        {"target": {"kind": "category", "name": "冰淇淋", "intent": "explore"},
         "lookups": [{"kind": "product", "query": "冰淇淋"}]},
        no_match,
        {"target": {"kind": "category", "name": "冰淇淋", "intent": "explore"},
         "lookups": [{"kind": "product", "query": "冰淇淋"}]},
        no_match,
    ])
    sid = create_session(client)
    baseline = client.get("/api/v1/cart").json()
    first = send_turn(client, sid, "来点零食")
    assert first["plan"] is None and first["plan_effect"] == "keep"
    assert client.get("/api/v1/cart").json() == baseline
    second = send_turn(client, sid, message, first)
    plan = second["plan"]
    assert len(plan["items"]) == 1 and plan["can_confirm"]
    item = plan["items"][0]
    assert item["name"] == shown[index]["name"]
    assert item["quantity"] == 1
    assert item["unit_price_fen"] == {CHIPS: 590, CRACKERS: 690}[item["sku_id"]]
    assert client.get("/api/v1/cart").json() == baseline
    ack = send_turn(client, sid, "好的", second)
    assert ack["plan_effect"] == "keep"
    assert all(row["status"] != "failed" for row in ack["action_results"])
    assert "已确认" not in ack["message"] and "已加购" not in ack["message"]
    assert client.get("/api/v1/cart").json() == baseline
    pending_plan = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    empty_pending = send_turn(client, sid, "来点冰淇淋", ack)
    assert empty_pending["plan_effect"] == "keep"
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] == pending_plan
    assert client.get("/api/v1/cart").json() == baseline

    confirmed = client.post(
        f"/api/v1/guide/tasks/{ack['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
              "expected_state_version": empty_pending["state_version"],
              "expected_session_version": empty_pending["session_version"],
              "selected_items": [{"sku_id": item["sku_id"], "quantity": 1}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    cart = client.get("/api/v1/cart").json()
    assert [(row["sku_id"], row["quantity"], row["unit_price_fen"])
            for row in cart["items"]] == [(item["sku_id"], 1, item["unit_price_fen"])]

    completed = client.get(f"/api/v1/guide/sessions/{sid}").json()
    before_plan = completed["plan"]
    empty = send_turn(client, sid, "来点冰淇淋", completed)
    assert empty["plan_effect"] == "keep"
    assert "薯片" not in empty["message"] and "饼干" not in empty["message"]
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"] == before_plan
    assert client.get("/api/v1/cart").json() == cart
    assert provider.remaining() == 0

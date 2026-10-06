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
PEACH_JUICE = "demo:cn-minute-maid-peach-450ml-bottle"


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


@pytest.mark.parametrize(
    "message,category,lookup_query,sku_id,tags,name_tokens",
    [
        ("来点零食", "零食", "零食", CRACKERS,
         ("零食", "即食"), ("苏打饼干", "100克", "盒装")),
        ("喝点甜的", "甜味饮品", "甜味", PEACH_JUICE,
         ("甜味", "甜而不腻"), ("桃汁饮料", "450毫升", "瓶装")),
    ],
)
def test_single_category_recommendation_uses_selected_sellable_sku_evidence(
    client, semantic_provider, tmp_path, monkeypatch,
    message, category, lookup_query, sku_id, tags, name_tokens,
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

    def fabricate(request):
        result = request["query_results"][0]
        match = next(row for row in result["matches"] if row["target_id"] == sku_id)
        assert match["stock_verified"] is True
        assert match["unknown_constraints"] == []
        assert all(tag in " ".join(match["evidence"]) for tag in tags)
        return {
            "reply": "这款非常受欢迎，销量很好，库存充足。",
            "display_refs": [match["ref"]],
        }

    provider = semantic_provider([
        {
            "target": {"kind": "category", "name": category, "intent": "explore"},
            "lookups": [{"kind": "product", "query": lookup_query}],
        },
        fabricate,
    ])
    sid = create_session(client)
    cart_before = client.get("/api/v1/cart").json()

    response = send_turn(client, sid, message)

    result = provider.requests[-1]["query_results"][0]
    selected = next(row for row in result["matches"] if row["target_id"] == sku_id)
    assert response["plan"] is None and response["plan_effect"] == "keep"
    assert selected["name"] in response["message"]
    assert all(token in selected["name"] for token in name_tokens)
    assert selected["evidence"][2] in response["message"]
    assert all(tag in response["message"] for tag in tags)
    assert all(term not in response["message"] for term in (
        "非常受欢迎", "销量", "库存充足", "beverage", "snack", "juice_drink",
        "soda_crackers", "匹配方式",
    ))
    assert client.get("/api/v1/cart").json() == cart_before
    assert provider.remaining() == 0


def test_unknown_sugar_content_returns_no_product_recommendation_or_plan(
    client, semantic_provider, tmp_path, monkeypatch
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
    provider = semantic_provider([
        {
            "target": {"kind": "category", "name": "低糖果汁", "intent": "explore"},
            "lookups": [{"kind": "product", "query": "桃汁低糖糖含量"}],
        },
        {
            "reply": "商品资料未提供糖含量，无法确认是否符合低糖要求。",
            "display_refs": [],
        },
    ])
    sid = create_session(client)
    cart_before = client.get("/api/v1/cart").json()

    response = send_turn(client, sid, "想喝低糖的果汁，有糖含量数据吗？")

    result = provider.requests[-1]["query_results"][0]
    assert result["matches"]
    assert all("nutrition" in row["unknown_constraints"] for row in result["matches"])
    assert response["message"] == "商品资料未提供糖含量，无法确认是否符合低糖要求。"
    assert response["plan"] is None and response["plan_effect"] == "keep"
    assert "美汁源" not in response["message"]
    assert client.get("/api/v1/cart").json() == cart_before
    assert provider.remaining() == 0

"""API evidence for the fixed live-model UI single-dish conversation."""
import json
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
repeat, stage = sys.argv[1:]
path = Path(__file__).with_name(f"ui-single-dish-{repeat}.json")
if stage == "initial":
    with sqlite3.connect(f"file:{ROOT.as_posix()}/data/runtime-langgraph/sale_guide.sqlite3?mode=ro", uri=True) as db:
        sid, owner = db.execute("SELECT session_id,owner_id FROM guide_sessions WHERE current_task_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1").fetchone()
    record = {"session_id": sid, "owner_id": owner, "provider": "live"}
else:
    record = json.loads(path.read_text(encoding="utf-8"))
with httpx.Client(base_url="http://127.0.0.1:8012", trust_env=False,
                  cookies={"sg_owner_id": record["owner_id"]}) as client:
    session = client.get(f"/api/v1/guide/sessions/{record['session_id']}?include_messages=1").json()
    cart = client.get("/api/v1/cart").json()
    record[stage] = {"session": session, "cart": cart}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    plan = session["plan"]
    if stage == "initial":
        assert len(plan["targets"]) == 1
        assert all(i["selected"] for i in plan["items"] if i["role"] == "required")
        assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
        assert plan["selected_total_fen"] == 1660
        reply = next(m["content"] for m in reversed(session["messages"]) if m["role"] == "assistant")
        assert "主推「番茄炒蛋」" in reply and "必需食材" in reply and "30 元预算内" in reply
    elif stage == "changed":
        assert plan["selected_total_fen"] == 2940
        assert {i["sku_id"] for i in plan["items"] if i["selected"]} == {
            "demo:tomato-fresh-500g", "demo:eggs-fresh-6pack", "demo:cooking-oil-500ml"}
        assert cart == record["initial"]["cart"]
    elif stage in ("ack", "ack-timeout"):
        assert plan == record["changed"]["session"]["plan"]
        assert cart == record["initial"]["cart"]
    elif stage == "confirmed":
        assert session["task_status"] == "completed"
        expected = {i["sku_id"]: i["quantity"] for i in record["initial"]["cart"]["items"]}
        for i in record["changed"]["session"]["plan"]["items"]:
            if i["selected"]:
                expected[i["sku_id"]] = expected.get(i["sku_id"], 0) + i["remaining_quantity"]
        assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == expected
        assert cart["total_price_fen"] - record["initial"]["cart"]["total_price_fen"] == 2940
    print(json.dumps({"repeat": repeat, "stage": stage, "session_id": record["session_id"],
                      "plan_version": plan["plan_version"], "cart_total": cart["total_price_fen"]}))

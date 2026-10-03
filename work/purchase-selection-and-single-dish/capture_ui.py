"""Record API snapshots corresponding to the UI-created test session.

SQLite is read only to identify the latest session; business assertions use API.
"""
import json
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
repeat, stage, *service = sys.argv[1:]
base_url = service[0] if service else "http://127.0.0.1:8012"
database = ROOT / ("work/purchase-selection-and-single-dish/ui-test.sqlite3" if base_url.endswith(":8013") else "data/runtime-langgraph/sale_guide.sqlite3")
destination = Path(__file__).with_name(f"ui-selection-{repeat}.json")
if stage in ("initial", "before"):
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
        sid, owner = db.execute("SELECT session_id,owner_id FROM guide_sessions WHERE current_task_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1").fetchone()
    record = json.loads(destination.read_text(encoding="utf-8")) if stage == "before" and destination.exists() else {"session_id": sid, "owner_id": owner, "base_url": base_url,
              "provider": "controlled ReactiveSemanticProvider" if base_url.endswith(":8013") else "live"}
else:
    record = json.loads(destination.read_text(encoding="utf-8"))
with httpx.Client(base_url=base_url, trust_env=False,
                  cookies={"sg_owner_id": record["owner_id"]}) as client:
    session = client.get(f"/api/v1/guide/sessions/{record['session_id']}").json()
    cart = client.get("/api/v1/cart").json()
    record[stage] = {"session": session, "cart": cart}
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if stage == "initial":
        assert all(i["selected"] for i in session["plan"]["items"] if i["role"] == "required")
        assert all(not i["selected"] for i in session["plan"]["items"] if i["role"] == "pantry")
        assert session["plan"]["selected_total_fen"] == 1660
    elif stage == "before":
        selected = [i for i in session["plan"]["items"] if i["selected"]]
        assert {i["sku_id"] for i in selected} == {"demo:eggs-fresh-6pack", "demo:cooking-oil-500ml"}
        assert session["plan"]["selected_total_fen"] == 2260
        if "initial" in record:
            assert cart == record["initial"]["cart"]
    elif stage == "restored":
        assert session["plan"] == record["before"]["session"]["plan"]
        assert cart == record["before"]["cart"]
    elif stage == "confirmed":
        assert session["task_status"] == "completed"
        before = record["before"]
        expected = {i["sku_id"]: i["quantity"] for i in before["cart"]["items"]}
        for i in before["session"]["plan"]["items"]:
            if i["selected"]:
                expected[i["sku_id"]] = expected.get(i["sku_id"], 0) + i["remaining_quantity"]
        assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == expected
        assert cart["total_price_fen"] - before["cart"]["total_price_fen"] == 2260
    print(json.dumps({"repeat": repeat, "stage": stage, "session_id": record["session_id"],
                      "plan_version": session["plan"]["plan_version"], "cart_total": cart["total_price_fen"]}))

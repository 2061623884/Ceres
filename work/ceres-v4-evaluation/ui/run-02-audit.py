import json, sqlite3
from pathlib import Path

ui = Path("work/ceres-v4-evaluation/ui").resolve()
db = ui / "runtime-run02.sqlite3"
report = json.loads((ui / "run-02" / "result.json").read_text(encoding="utf-8"))
journeys = []
for item in report["journeys"]:
    plan = item.get("plan_before_confirm", {}).get("plan") or {}
    rows = []
    for step in item.get("steps", []):
        completion = [event for event in step.get("events", []) if event.get("type") == "turn.completed"]
        rows.append({
            "label": step["label"],
            "final_reply_ms": step.get("final_reply_ms"),
            "performance_passed": step.get("performance_passed"),
            "http_status": step.get("http_status"),
            "event_types": [event.get("type") for event in step.get("events", [])],
            "completion_event_count": len(completion),
            "cart_items_after_reply": len((step.get("cart_after_reply") or {}).get("items", [])),
        })
    visible_text = item.get("visible_text", "")
    journeys.append({
        "name": item["name"],
        "status": item["status"],
        "stage": item.get("stage"),
        "error": item.get("error"),
        "performance_passed": item.get("performance_passed"),
        "steps": rows,
        "writes_before_confirm": item.get("writes_before_confirm"),
        "guide_plan": {
            "keys": list(plan.keys()),
            "can_confirm": plan.get("can_confirm"),
            "items": plan.get("items"),
            "validation": plan.get("validation"),
            "status": plan.get("status"),
        },
        "confirmation_status": (item.get("confirmation") or {}).get("status"),
        "final_cart": item.get("final_cart"),
        "console_errors": item.get("console_errors"),
        "visible_text_tail": visible_text[-1200:],
    })
owner = report["journeys"][0]["bootstrap"]["owner_id"]
uri = db.as_uri() + "?mode=ro"
con = sqlite3.connect(uri, uri=True)
tables = con.execute("select name from sqlite_master where type='table' order by name").fetchall()
owner_rows = []
for (name,) in tables:
    quoted = '"' + name.replace('"', '""') + '"'
    cols = [row[1] for row in con.execute("pragma table_info(" + quoted + ")").fetchall()]
    if "owner_id" in cols:
        count = con.execute("select count(*) from " + quoted + " where owner_id=?", (owner,)).fetchone()[0]
        owner_rows.append({"table": name, "rows": count})
con.close()
print(json.dumps({
    "product_head": report["product_head"],
    "automatic_browser_acceptance": report["automatic_browser_acceptance"],
    "runner_sha256": report["runner_sha256"],
    "runtime_receipt_sha256": report["runtime_receipt_sha256"],
    "database_path": str(db),
    "database_open_mode": "read-only",
    "bootstrap_owner_id": owner,
    "owner_id_tables": owner_rows,
    "owner_matches": [row for row in owner_rows if row["rows"]],
    "journeys": journeys,
}, ensure_ascii=False, indent=2))
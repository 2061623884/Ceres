"""Two fixed conversations on the deployed API, with independent owner cookies."""

import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests"))
from app.core.config import get_settings
from support import create_session, parse_sse_events, terminal_payload

settings = get_settings()
SKUS = {"demo:snack-original-potato-chips-70g-bag": 590,
        "demo:snack-soda-crackers-100g-box": 690}
CONVERSATION = ["来点零食", "就第一个", "好的", "来点冰淇淋", "来点冰淇淋"]
for repeat in (1, 2):
    record = {"repeat": repeat, "model": settings.llm_model,
              "index": json.loads((ROOT / "data/retrieval_index-langgraph/current.json").read_text()),
              "inputs": CONVERSATION, "turns": []}
    destination = Path(__file__).with_name(f"live-{repeat}.json")
    with httpx.Client(base_url="http://127.0.0.1:8012", trust_env=False, timeout=100) as client:
        sid = create_session(client)
        record.update(session_id=sid, owner_id=client.cookies["sg_owner_id"])
        baseline = client.get("/api/v1/cart").json()
        assert baseline["items"] == []
        previous = {}
        for step, message in enumerate(CONVERSATION):
            request_id = str(uuid.uuid4())
            body = {"request_id": request_id, "message": message,
                    "expected_task_id": previous.get("task_id"),
                    "expected_state_version": previous.get("state_version", 0),
                    "expected_session_version": previous.get("session_version")}
            started = time.perf_counter()
            chunks, arrivals = [], []
            with client.stream("POST", f"/api/v1/guide/sessions/{sid}/turns/stream", json=body) as response:
                response.raise_for_status()
                for chunk in response.iter_text():
                    chunks.append(chunk)
                    arrivals.append(round((time.perf_counter() - started) * 1000))
            events = parse_sse_events("".join(chunks))
            row = {"input": message, "request_id": request_id,
                   "elapsed_ms": round((time.perf_counter() - started) * 1000),
                   "first_chunk_ms": arrivals[0], "events": events,
                   "cart": client.get("/api/v1/cart").json(),
                   "session": client.get(f"/api/v1/guide/sessions/{sid}").json()}
            with sqlite3.connect(f"file:{settings.runtime_db_path.as_posix()}?mode=ro", uri=True) as db:
                context = db.execute("SELECT context_json FROM guide_semantic_contexts WHERE session_id=?", (sid,)).fetchone()
                row["semantic_context"] = json.loads(context[0]) if context else None
                row["traces"] = [dict(zip(("phase", "model_mode", "duration_ms", "output_summary", "error"), t)) for t in db.execute("SELECT phase,model_mode,duration_ms,output_summary,error FROM trace_events WHERE request_id=? ORDER BY created_at", (request_id,))]
            record["turns"].append(row)
            destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            previous = terminal_payload(events)
            assert not any(r["status"] == "failed" for r in previous["action_results"]), previous
            print(json.dumps({"repeat": repeat, "step": step, "message": message,
                              "elapsed_ms": row["elapsed_ms"], "reply": previous["message"]}, ensure_ascii=False), flush=True)
            if step == 0:
                shown = row["semantic_context"]["displayed_candidates"]
                assert shown and {r["target_id"] for r in shown} <= set(SKUS), shown
                assert all(r["kind"] == "product" for r in shown)
                assert previous["plan"] is None and previous["plan_effect"] == "keep"
                assert row["cart"] == baseline
            elif step == 1:
                plan = previous["plan"]
                assert len(plan["items"]) == 1 and plan["can_confirm"]
                item = plan["items"][0]
                assert item["sku_id"] == shown[0]["target_id"]
                assert item["quantity"] == 1 and item["unit_price_fen"] == SKUS[item["sku_id"]]
                assert row["cart"] == baseline
                selected_plan = row["session"]["plan"]
            elif step == 2:
                assert previous["plan_effect"] == "keep"
                assert "已确认" not in previous["message"] and "已加购" not in previous["message"]
                assert row["cart"] == baseline and row["session"]["plan"] == selected_plan
            else:
                assert previous["plan_effect"] == "keep"
                assert row["semantic_context"].get("displayed_candidates", []) == []
                assert "冰淇淋" in previous["message"]
                assert "薯片" not in previous["message"] and "饼干" not in previous["message"]
                assert row["session"]["plan"] == selected_plan
                assert row["cart"] == (baseline if step == 3 else confirmed_cart)
                reads = [r for r in previous["action_results"] if r["type"] == "read_only"]
                if step == 3:
                    assert len(reads) == 1 and reads[0]["status"] == "completed", reads
            if step == 3:
                started = time.perf_counter()
                confirmed = client.post(f"/api/v1/guide/tasks/{previous['task_id']}/confirm",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    json={"plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
                          "expected_state_version": previous["state_version"],
                          "expected_session_version": previous["session_version"],
                          "selected_items": [{"sku_id": item["sku_id"], "quantity": 1}]})
                record["confirmation"] = {"action": "明确点击确认加购", "status_code": confirmed.status_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000), "result": confirmed.json()}
                confirmed_cart = client.get("/api/v1/cart").json()
                record["confirmed_cart"] = confirmed_cart
                destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                assert confirmed.status_code == 200, confirmed.text
                assert [(r["sku_id"], r["quantity"], r["unit_price_fen"]) for r in confirmed_cart["items"]] == [(item["sku_id"], 1, SKUS[item["sku_id"]])]
                previous = client.get(f"/api/v1/guide/sessions/{sid}").json()
                selected_plan = previous["plan"]
        record["passed"] = True
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

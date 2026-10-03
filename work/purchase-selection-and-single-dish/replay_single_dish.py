"""Two independent fixed single-dish runs on the deployed API, no retries."""
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))
from support import create_session, parse_sse_events, terminal_payload

for repeat in ([int(sys.argv[1])] if len(sys.argv) > 1 else (1, 2)):
    record = {"repeat": repeat, "turns": []}
    path = Path(__file__).with_name(f"single-dish-{repeat}.json")
    with httpx.Client(base_url="http://127.0.0.1:8012", trust_env=False, timeout=100) as client:
        sid = create_session(client)
        record.update(session_id=sid, owner_id=client.cookies["sg_owner_id"])
        baseline = client.get("/api/v1/cart").json()
        assert baseline["items"] == []
        previous = {}
        for message in ("今晚自己做一道菜，预算30元，没有忌口，你帮我推荐一道菜", "好的"):
            started = time.perf_counter()
            chunks, arrivals = [], []
            with client.stream("POST", f"/api/v1/guide/sessions/{sid}/turns/stream", json={
                "request_id": str(uuid.uuid4()), "message": message,
                "expected_task_id": previous.get("task_id"),
                "expected_state_version": previous.get("state_version", 0),
                "expected_session_version": previous.get("session_version"),
            }) as response:
                response.raise_for_status()
                for chunk in response.iter_text():
                    chunks.append(chunk)
                    arrivals.append(round((time.perf_counter() - started) * 1000))
            events = parse_sse_events("".join(chunks))
            session = client.get(f"/api/v1/guide/sessions/{sid}").json()
            row = {"input": message, "elapsed_ms": round((time.perf_counter() - started) * 1000),
                   "first_chunk_ms": arrivals[0], "events": events,
                   "session": session, "cart": client.get("/api/v1/cart").json()}
            record["turns"].append(row)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            previous = terminal_payload(events)
            assert not any(a["status"] == "failed" for a in previous["action_results"]), previous
            assert row["cart"] == baseline
            print(json.dumps({"repeat": repeat, "input": message, "elapsed_ms": row["elapsed_ms"],
                              "reply": previous["message"]}, ensure_ascii=False), flush=True)
            if message == "好的":
                assert session["plan"] == saved_plan
                continue
            plan = session["plan"]
            assert plan and len(plan["targets"]) == 1 and plan["can_confirm"]
            assert f"主推「{plan['targets'][0]['name']}」" in previous["message"]
            assert "必需食材" in previous["message"] and "预算内" in previous["message"]
            assert f"{plan['selected_total_fen'] / 100:.2f}" in previous["message"]
            assert all(i["selected"] for i in plan["items"] if i["role"] == "required")
            assert all(not i["selected"] for i in plan["items"] if i["role"] == "pantry")
            pantry = next(i for i in plan["items"] if i["role"] == "pantry")
            edits = [{"sku_id": i["sku_id"], "quantity": i["quantity"],
                      "selected": i["selected"] or i["sku_id"] == pantry["sku_id"]} for i in plan["items"]]
            revision = client.post(f"/api/v1/guide/tasks/{session['task_id']}/plan-revisions", json={
                "request_id": str(uuid.uuid4()), "expected_session_version": session["session_version"],
                "expected_state_version": session["state_version"], "base_plan_id": plan["plan_id"],
                "base_plan_version": plan["plan_version"], "coverage_intent": "partial_ok", "items": edits,
            })
            revision.raise_for_status()
            previous = client.get(f"/api/v1/guide/sessions/{sid}").json()
            saved_plan = previous["plan"]
            record["revision"] = revision.json()
            record["products"] = [client.get(f"/api/v1/products/{i['sku_id']}").json() for i in saved_plan["items"]]
            assert all(p["price_fen"] == i["unit_price_fen"] for p, i in zip(record["products"], saved_plan["items"]))
            assert client.get("/api/v1/cart").json() == baseline
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        session = client.get(f"/api/v1/guide/sessions/{sid}").json()
        plan = session["plan"]
        selected = [{"sku_id": i["sku_id"], "quantity": i["remaining_quantity"]}
                    for i in plan["items"] if i["selected"] and i["remaining_quantity"] > 0]
        started = time.perf_counter()
        confirmation = client.post(f"/api/v1/guide/tasks/{session['task_id']}/confirm", json={
            "plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
            "expected_state_version": session["state_version"],
            "expected_session_version": session["session_version"], "selected_items": selected,
        }, headers={"Idempotency-Key": str(uuid.uuid4())})
        record.update(confirm=confirmation.json(), confirm_ms=round((time.perf_counter()-started)*1000),
                      final_cart=client.get("/api/v1/cart").json())
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        confirmation.raise_for_status()
        cart = record["final_cart"]
        assert {i["sku_id"]: i["quantity"] for i in cart["items"]} == {i["sku_id"]: i["quantity"] for i in selected}
        assert cart["total_price_fen"] == plan["outstanding_total_fen"]
        print(json.dumps({"repeat": repeat, "cart_total": cart["total_price_fen"],
                          "confirm_ms": record["confirm_ms"]}), flush=True)

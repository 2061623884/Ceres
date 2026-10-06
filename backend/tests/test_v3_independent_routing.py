"""Once-only independent dialogue checks after candidate06 is frozen."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from support import post_turn
from support.v2_fixture import source_database_path  # noqa: F401
from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, opening, send, new_order

pytestmark = pytest.mark.skipif(not os.environ.get("CERES_V3_INDEPENDENT_EVIDENCE_DIR"),
                                reason="Dedicated evaluator enables only after candidate freeze")


def test_independent_dialogue_phenomena(client, monkeypatch, semantic_provider):
    destination = Path(os.environ["CERES_V3_INDEPENDENT_EVIDENCE_DIR"])
    destination.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((Path(__file__).resolve().parents[2] / "evals/v3/holdout-cases.json").read_text(encoding="utf-8"))
    original = httpx.Client.send
    upstream = []

    def capture(self, request, **kwargs):
        if request.url.path != "/v1/systemone":
            return original(self, request, **kwargs)
        row = {"request": json.loads(request.content)}
        upstream.append(row)
        try:
            response = original(self, request, **kwargs)
            row.update(http_status=response.status_code, raw_response=response.text)
            row["response"] = response.json()
            return response
        except httpx.HTTPError as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            raise

    monkeypatch.setattr(httpx.Client, "send", capture)
    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="本轮墨墨模型是受控边界，不进行业务写入。", tool_calls=[]))])))))
    rows = []
    active = None
    failure = None
    try:
        for case in frozen["cases"]:
            active = {"case_id": case["id"], "expected": case["expected"], "passed": False}
            rows.append(active)
            role = "momo" if case["state"]["current_role"].startswith("Momo") else "keke"
            semantic_provider([{"reply": "本轮角色模型是受控边界，不进行业务写入。"}] * 5)
            chat = opening(client, role=role)
            extra = {}
            order = new_order(client) if case["state"]["selected_object"] else None
            if order:
                extra["order_id"] = order["order_id"]
            preparation = []
            active.update(message=case["state"]["utterance"], preparation=preparation, actual_order=order)
            prepared = True
            if case["id"] == "HO01":
                semantic_provider([{"reply": case["state"]["recent_dialogue"][0]["content"]},
                                   {"reply": "可以继续选购露营零食。"}])
                previous = post_turn(client, chat["guide_session_id"], "我们之前聊过订单状态")
                prepared = previous.status_code == 200
                preparation.append({"kind": "actual Guide API / controlled role response",
                                    "http_status": previous.status_code, "body": previous.text})
            if case["id"] == "HO03":
                index = len(upstream)
                previous = send(client, chat, "帮我取消那个", "HO03-clarification-setup")
                setup = {"kind": "actual preceding Kev clarification; separate setup observation",
                         "http_status": previous.status_code, "sse": previous.text,
                         "upstream": upstream[index:], "expected": "clarify", "passed": False}
                preparation.append(setup)
                parsed = events(previous)
                prepared = parsed[0]["payload"].get("decision") == "clarify"
                setup["passed"] = prepared
            before_orders = client.get("/api/v1/orders").json()
            business_before = None
            if case["expected"] == "suggest_switch":
                guide = client.get(f"/api/v1/guide/sessions/{chat['guide_session_id']}").json()
                business_before = {"guide": {key: guide[key] for key in
                                   ("task_id", "state_version", "session_version", "plan")},
                                   "cart": client.get("/api/v1/cart").json()}
            index = len(upstream)
            response = send(client, chat, case["state"]["utterance"], case["id"], **extra)
            active.update(http_status=response.status_code, raw_sse=response.text, upstream=upstream[index:])
            parsed = events(response)
            route = parsed[0]["payload"] if parsed else {}
            after_orders = client.get("/api/v1/orders").json()
            stayed = client.get(f"/api/v1/chat/openings/{chat['opening_id']}").json()["role"] == role
            business_paused = True
            if case["expected"] == "suggest_switch":
                guide = client.get(f"/api/v1/guide/sessions/{chat['guide_session_id']}").json()
                business_after = {"guide": {key: guide[key] for key in
                                  ("task_id", "state_version", "session_version", "plan")},
                                  "cart": client.get("/api/v1/cart").json()}
                terminal = parsed[-1]
                business_paused = (terminal["type"] == "turn.completed" and
                                   terminal["payload"].get("business_not_run") is True and
                                   business_before == business_after)
                active.update(terminal=terminal, business_before=business_before,
                              business_after=business_after, business_paused=business_paused)
            active.update({"case_id": case["id"], "scenario_group": case["scenario_group"],
                         "expected": case["expected"], "actual": route,
                         "preparation": preparation, "actual_order": order,
                         "passed": prepared and response.status_code == 200 and
                                   route.get("status") == "completed" and route.get("decision") == case["expected"]
                                   and stayed and before_orders == after_orders and business_paused,
                         "role_unchanged_without_consent": stayed,
                         "orders_before": before_orders, "orders_after": after_orders})
            active = None
        assert len(rows) == 4
        assert all(row["passed"] for row in rows), [(row["case_id"], row["actual"], row["preparation"]) for row in rows if not row["passed"]]
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "message": str(exc)}
        if active is not None:
            active.update(error=failure)
        raise
    finally:
        raw = (json.dumps({"case_version": frozen["version"], "requested_rows": 4,
            "scope": "First independent candidate check; real Kev/public API, controlled role/memory models; setup observations separate",
            "rows": rows, "all_upstream": upstream, "failure": failure}, ensure_ascii=False, indent=2)+"\n").encode("utf-8")
        (destination / "results.json").write_bytes(raw)
        (destination / "results.sha256").write_text(hashlib.sha256(raw).hexdigest()+"\n", encoding="utf-8")

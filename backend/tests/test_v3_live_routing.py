"""Explicitly enabled API routing performance, real Kev / controlled role models."""
import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import httpx
import pytest

from support import post_turn
from support.v2_fixture import source_database_path  # noqa: F401
from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, opening, send, new_order

pytestmark = pytest.mark.skipif(not os.environ.get("CERES_V3_ROUTE_EVIDENCE_DIR"),
                                reason="Dedicated evaluator must enable real Kev API measurement")


def test_real_kev_fixed_public_contexts(client, monkeypatch, semantic_provider):
    destination = Path(os.environ["CERES_V3_ROUTE_EVIDENCE_DIR"])
    destination.mkdir(parents=True, exist_ok=True)
    core = json.loads((Path(__file__).resolve().parents[2] / "evals/v3/core-cases.json").read_text(encoding="utf-8"))
    cases = [c for c in core["cases"] if "state" in c]
    semantic_provider([lambda request: {"reply": (
        "要移除采购清单里的可乐吗？" if request["user_message"] == "清单里的可乐不要了"
        else "本轮只验证真实路由；角色模型是受控边界。"
    )}] * 40)
    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="受控订单/政策回答；不进行写入。", tool_calls=[]))])))))
    original = httpx.Client.send
    upstream = []

    def capture(self, request, **kwargs):
        if request.url.path != "/v1/systemone":
            return original(self, request, **kwargs)
        row = {"request": json.loads(request.content)}
        upstream.append(row)
        try:
            response = original(self, request, **kwargs)
            row.update(http_status=response.status_code, response=response.json())
            return response
        except httpx.HTTPError as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            raise

    monkeypatch.setattr(httpx.Client, "send", capture)
    rows = []
    # Two predeclared passes are a performance sample, never retry on a failure.
    for repetition in range(2):
        for case in cases:
            role = "momo" if case["state"]["current_role"].startswith("Momo") else "keke"
            chat = opening(client, role=role)
            extra = {}
            selected = case["state"]["selected_object"]
            if selected and selected["kind"] == "placed_order":
                extra["order_id"] = new_order(client)["order_id"]
            if case["id"] == "R02":
                extra["view_context"] = {"page": "product", "product_id": "demo:cn-coke-zero-500ml-bottle"}
            if case["id"] == "R06":
                post_turn(client, chat["guide_session_id"], "清单里的可乐不要了")
            if case["id"] == "R10":
                post_turn(client, chat["guide_session_id"], "用户之前在问订单到哪了，现在准备换话题")
            before = len(upstream)
            started = perf_counter()
            row = {"case_id": case["id"], "repetition": repetition, "expected": case["expected"],
                   "actual": {"status": "request_failed", "decision": None, "route_ms": None},
                   "passed": False}
            try:
                response = send(client, chat, case["state"]["utterance"], f"{case['id']}-{repetition}", **extra)
                parsed = events(response)
                route = parsed[0]["payload"] if parsed else {}
                row.update(actual=route, raw_sse=response.text,
                           passed=route.get("status") == "completed" and route.get("decision") == case["expected"])
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                row.update(api_wall_ms=(perf_counter() - started) * 1000, upstream=upstream[before:])
                rows.append(row)
                (destination / "results.json").write_text(json.dumps({"case_version": core["version"],
                    "scope": "actual API route_ms includes context preparation, real network and parsed decision; role and memory models controlled",
                    "requested_rows": len(cases) * 2, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert len(rows) == 22
    assert all(row["passed"] for row in rows), [(r["case_id"], r["repetition"], r["actual"]) for r in rows if not r["passed"]]

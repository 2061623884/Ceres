"""Opt-in real Kev + role model API samples; raw requests/responses retained."""
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

import httpx
import pytest

from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, opening, send, new_order
from support.v2_fixture import source_database_path  # noqa: F401
from test_semantic_phase1_purchase import indexed_client  # noqa: F401


pytestmark = pytest.mark.skipif(not os.environ.get("CERES_V3_LIVE_EVIDENCE_DIR"),
                                reason="Dedicated evaluator must explicitly enable real model sampling")


@pytest.mark.parametrize("case_id,role,message,expected,source_id", [
    ("R01", "keke", "想买两瓶无糖可乐", "stay_current", None),
    ("R01-named-product-variant", "keke", "想买一盒新鲜鸡蛋", "stay_current", None),
    ("R02", "keke", "这个商品不喜欢能退吗", "stay_current", "P-RET-01"),
    ("R03", "momo", "一般签收后几天内能退", "stay_current", "P-RET-01"),
    ("H01", "keke", "这单到哪了", "suggest_switch", None),
])
def test_real_role_and_kev_sample(indexed_client, monkeypatch, case_id, role, message, expected, source_id):
    # The opt-in evaluator uses the recorded OpenAI 3.19.2 runtime. Collection
    # of ordinary tests must also work with the application's older SDK minimum.
    from openai import DefaultHttpxClient
    client = indexed_client
    out = Path(os.environ["CERES_V3_LIVE_EVIDENCE_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    upstream = []
    # Save both before patching: the installed SDK has its own HTTP client.
    clients = [(httpx.Client, httpx.Client.send), (DefaultHttpxClient, DefaultHttpxClient.send)]

    def capture_send(original_send):
        def capture(self, request, **kwargs):
            if request.url.host == "testserver":
                return original_send(self, request, **kwargs)
            row = {"url": str(request.url), "method": request.method,
                   "request_body": request.content.decode(), "buffered_stream_capture": True,
                   "client_boundary": type(self).__module__ + "." + type(self).__name__}
            upstream.append(row)
            started = perf_counter()
            try:
                response = original_send(self, request, **kwargs)
                response.read()
                row.update(http_status=response.status_code, response_body=response.text)
                return response
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                row["elapsed_ms"] = (perf_counter() - started) * 1000
        return capture

    for client_type, original_send in clients:
        monkeypatch.setattr(client_type, "send", capture_send(original_send))
    chat = opening(client, role=role)
    order = new_order(client) if case_id == "H01" else None
    before = client.get("/api/v1/orders").json()
    started = perf_counter()
    extra = {"order_id": order["order_id"]} if order else {}
    if case_id == "R02":
        extra["view_context"] = {"page": "product", "product_id": "demo:cn-coke-zero-500ml-bottle"}
    row = {"case_id": case_id, "message": message, "expected_route": expected,
           "passed": False,
           "opening": chat, "actual_order": order, "upstream": upstream,
           "clock_scope": "in-process public API receipt to fully drained terminal SSE; no browser evidence",
           "memory_model": "controlled empty output; actual worker drained; both role main models real"}
    try:
        response = send(client, chat, message, case_id, **extra)
        row.update(api_http_status=response.status_code, sse=response.text,
                   backend_api_wall_ms=(perf_counter() - started) * 1000)
        parsed = events(response)
        route = parsed[0]["payload"] if parsed else {}
        row["route"] = route
        assert response.status_code == 200
        assert route["status"] == "completed", route
        assert route["decision"] == expected, route
        if order:
            assert client.get(f"/api/v1/chat/openings/{chat['opening_id']}").json()["role"] == "keke"
            switched_at = perf_counter()
            switched = client.post(f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream", json={
                "target_role": "momo", "handoff_id": route["handoff_id"], "accept": True})
            row.update(handoff_sse=switched.text, handoff_backend_wall_ms=(perf_counter() - switched_at) * 1000)
            parsed = events(switched)
        assert parsed[-1]["type"] == "turn.completed", parsed[-1]
        assert parsed[-1]["payload"].get("answer_status") != "failed", parsed[-1]
        assert not any(event["type"] in ("error", "turn.stopped") for event in parsed)
        if case_id == "R01":
            first_turn = parsed[-1]["payload"]
            assert first_turn["plan"] is None, first_turn
            assert first_turn["committed"] is False, first_turn
            assert client.get("/api/v1/cart").json()["items"] == []
            assert client.get("/api/v1/orders").json() == before
            card = next(card for card in first_turn["product_cards"]
                        if card["sku_id"] == "demo:cn-coke-zero-500ml-bottle")
            selected_message = f"就选{card['name']}，两瓶"
            row.update(selection_message=selected_message, selected_card=card)
            selected_at = perf_counter()
            selected = send(client, chat, selected_message, "R01-selected", view_context={
                "page": "product", "product_id": card["sku_id"]})
            row.update(selection_http_status=selected.status_code, selection_sse=selected.text,
                       selection_backend_wall_ms=(perf_counter() - selected_at) * 1000)
            parsed = events(selected)
            row["selection_route"] = parsed[0]["payload"]
            assert selected.status_code == 200, selected.text
            assert row["selection_route"]["status"] == "completed", row["selection_route"]
            assert row["selection_route"]["decision"] == "stay_current", row["selection_route"]
            assert parsed[-1]["type"] == "turn.completed", parsed[-1]
            assert parsed[-1]["payload"].get("answer_status") != "failed", parsed[-1]
            assert not any(event["type"] in ("error", "turn.stopped") for event in parsed)
        if case_id in ("R01", "R01-named-product-variant"):
            plan = parsed[-1]["payload"]["plan"]
            assert plan is not None, parsed[-1]
            assert len(plan["items"]) == 1, plan
            item = plan["items"][0]
            if case_id == "R01":
                assert item["sku_id"] == "demo:cn-coke-zero-500ml-bottle", item
                assert item["ingredient_ids"] == ["cola"], item
                assert item["quantity"] == 2, item
            else:
                assert item["sku_id"] in {"demo:eggs-fresh-6pack", "demo:eggs-10pack"}, item
                assert item["quantity"] == 1, item
            detail = client.get(f"/api/v1/products/{item['sku_id']}")
            assert detail.status_code == 200
            row["actual_product"] = detail.json()
            assert detail.json()["sellable"] is True
            assert detail.json()["ingredient_ids"] == (["cola"] if case_id == "R01" else ["egg"])
            assert detail.json()["price_fen"] == item["unit_price_fen"]
            assert detail.json()["available_qty"] >= item["quantity"]
        if source_id:
            text_field = "message" if role == "keke" else "final_text"
            assert source_id in parsed[-1]["payload"][text_field], parsed[-1]
        row["orders_after"] = client.get("/api/v1/orders").json()
        assert row["orders_after"] == before
        assert client.get("/api/v1/cart").json()["items"] == []
        row["passed"] = True
    except Exception as exc:
        # Persist the sample failure, then let pytest retain the original error.
        row.update(passed=False, error_type=type(exc).__name__, assertion=str(exc))
        raise
    finally:
        if "backend_api_wall_ms" not in row:
            row["backend_api_wall_ms"] = (perf_counter() - started) * 1000
            row["clock_scope"] = "public API call failed before terminal SSE; failure duration, not successful reply latency"
        row["upstream"] = upstream
        raw = json.dumps(row, ensure_ascii=False, indent=2) + "\n"
        encoded = raw.encode("utf-8")
        (out / f"{case_id}.json").write_bytes(encoded)
        (out / f"{case_id}.sha256").write_text(hashlib.sha256(encoded).hexdigest() + "\n")

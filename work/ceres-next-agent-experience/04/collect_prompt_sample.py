from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from _pytest.monkeypatch import MonkeyPatch

CREDENTIAL_VALUE = re.compile(
    r'''(?i)(["']?(?:api_key|openai_api_key|embedding_api_key|internal_admin_token|access_token|refresh_token|authorization|x-internal-token|secret_key)["']?\s*[:=]\s*["']?)[^"',\s}\]]+'''
)
BODY_FIELDS = (
    "model", "messages", "tools", "tool_choice", "temperature", "top_p",
    "max_tokens", "response_format", "stream", "stream_options",
)


class CapturingTransport(httpx.BaseTransport):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        self.calls: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request_body = request.read()
        payload = json.loads(request_body)
        started = time.perf_counter()
        record = {
            "request": {key: payload[key] for key in BODY_FIELDS if key in payload},
            "response_status": None,
            "response_model": None,
            "response_choices": [],
            "usage": None,
            "request_latency_ms": None,
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                trust_env=False,
            ) as client:
                response = client.post(
                    str(request.url),
                    headers=dict(request.headers),
                    content=request_body,
                )
        except Exception as exc:
            record["request_latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            record["transport_error_type"] = type(exc).__name__
            self.calls.append(record)
            raise

        record["request_latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        record["response_status"] = response.status_code
        body = response.content
        if response.status_code < 400:
            if payload.get("stream"):
                content_parts: list[str] = []
                finish_reason = None
                for line in body.decode("utf-8", errors="replace").splitlines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event.get("model"):
                        record["response_model"] = event["model"]
                    if isinstance(event.get("usage"), dict):
                        record["usage"] = event["usage"]
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if isinstance(delta.get("content"), str):
                            content_parts.append(delta["content"])
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                record["response_choices"] = [{
                    "message": {"content": "".join(content_parts)},
                    "finish_reason": finish_reason,
                }]
            else:
                data = response.json()
                record["response_model"] = data.get("model")
                record["usage"] = data.get("usage") if isinstance(data.get("usage"), dict) else None
                for choice in data.get("choices") or []:
                    message = choice.get("message") or {}
                    record["response_choices"].append({
                        "message": {
                            "content": message.get("content"),
                            "tool_calls": message.get("tool_calls"),
                        },
                        "finish_reason": choice.get("finish_reason"),
                    })
        else:
            try:
                error = response.json().get("error")
                if isinstance(error, dict):
                    record["response_error"] = {
                        key: error.get(key) for key in ("code", "type", "message") if key in error
                    }
            except (ValueError, json.JSONDecodeError):
                record["response_error"] = {"body_present": bool(body)}
        self.calls.append(record)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=body,
            request=request,
        )


def module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def project_plan(plan):
    if not isinstance(plan, dict):
        return None
    return {
        "targets": [
            {key: target.get(key) for key in ("kind", "name", "quantity") if key in target}
            for target in plan.get("targets", [])
        ],
        "items": [
            {key: item.get(key) for key in ("name", "quantity", "unit_price_fen", "selected") if key in item}
            for item in plan.get("items", [])
        ],
        "selected_total_fen": plan.get("selected_total_fen"),
        "status": plan.get("status"),
    }


def project_public(body):
    return {
        "message": body.get("message"),
        "pending_clarifications": body.get("pending_clarifications"),
        "product_cards": body.get("product_cards"),
        "plan": project_plan(body.get("plan")),
        "plan_effect": body.get("plan_effect"),
        "task_present": bool(body.get("task_id")),
        "action_results": body.get("action_results"),
    }


def read_trace(client, trace_id: str, headers: dict) -> list[dict]:
    response = client.get(f"/api/v1/internal/traces/{trace_id}", headers=headers)
    if response.status_code != 200:
        return [{"trace_read_status": response.status_code}]
    events = response.json().get("events", [])
    fields = (
        "phase", "call_number", "stage", "status", "duration_ms", "capability",
        "branch", "code", "criteria_version",
    )
    return [{key: event[key] for key in fields if key in event} for event in events]


def run_case(tree: Path, case_id: str, output_dir: Path) -> dict:
    sys.path.insert(0, str(tree / "backend"))
    sys.path.insert(0, str(tree))
    sys.path.insert(0, str(tree / "backend" / "tests"))

    conftest = module_from(tree / "backend" / "tests" / "conftest.py", "sample_conftest")
    semantic_tests = __import__("test_semantic_phase1_purchase")
    support = __import__("support", fromlist=["create_session", "send_turn"])

    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "sample.sqlite3"
    db_url = "sqlite:///" + db_path.as_posix()
    monkeypatch = MonkeyPatch()
    monkeypatch.setenv("INTERNAL_ENABLED", "true")
    trace_token = uuid.uuid4().hex
    monkeypatch.setenv("INTERNAL_ADMIN_TOKEN", trace_token)
    source_db = tree / "data" / "sale_guide.db"
    route = {
        "snack_type_first": "category_exploration",
        "same_category_cola_filter": "purchase_modify",
        "keke_return_policy": "facts_qa",
        "momo_selected_order_return": "chat",
    }[case_id]
    kev = conftest.kev_api.__wrapped__(monkeypatch)
    kev["choices"]["capability"] = route

    client_gen = conftest.client.__wrapped__(db_url, monkeypatch, source_db, kev)
    started = time.perf_counter()
    capture = None
    sample = {
        "case_id": case_id,
        "tree_head": os.environ.get("CERES_TREE_HEAD"),
        "prompt_source_sha256": {
            "backend/app/prompts/semantic.py": hashlib.sha256(
                (tree / "backend" / "app" / "prompts" / "semantic.py").read_bytes()
            ).hexdigest(),
            "Mercury/mercury/prompt.py": hashlib.sha256(
                (tree / "Mercury" / "mercury" / "prompt.py").read_bytes()
            ).hexdigest(),
        },
        "route_mode": "controlled Kev route; actual configured semantic/Mercury model calls",
        "controlled_keke_capability": route,
        "status": "running",
        "semantic_calls": [],
        "turns": [],
        "kev_choices": [],
    }
    try:
        client = next(client_gen)
        indexed_client = semantic_tests.indexed_client.__wrapped__(
            client, db_url, monkeypatch, output_dir / "index-build"
        )
        from app.core.config import get_settings
        from app.llm.live_semantic_provider import LiveSemanticProvider
        from app.llm.openai_transport import OpenAICompatTransport

        settings = get_settings()
        endpoint = urlsplit(settings.openai_base_url)
        capture = CapturingTransport(float(settings.llm_timeout))
        provider = LiveSemanticProvider(
            settings, OpenAICompatTransport(settings, transport=capture)
        )
        monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)
        sample["model"] = settings.llm_model
        sample["endpoint"] = (
            endpoint.scheme + "://" + endpoint.hostname
            + ((":" + str(endpoint.port)) if endpoint.port else "") + endpoint.path
        )
        sample["retrieval"] = {
            "mode": settings.retrieval_mode,
            "index_path_is_case_local": True,
            "index_method": "existing indexed_client fixture; embedding=None; vectors=None; lexical",
        }
        headers = {"X-Internal-Token": trace_token}

        def save_turn(label: str, message: str, session_id: str, previous=None, **extra):
            before = len(capture.calls)
            kev_before = len(kev["calls"])
            turn_started = time.perf_counter()
            body = support.send_turn(
                indexed_client, session_id, message, previous,
                request_id=f"{case_id}-{label}-{uuid.uuid4().hex[:8]}", **extra,
            )
            elapsed = round((time.perf_counter() - turn_started) * 1000, 1)
            trace_id = body.get("trace_id")
            sample["turns"].append({
                "label": label,
                "user_message": message,
                "public_output": project_public(body),
                "turn_elapsed_ms": elapsed,
                "trace_phases": read_trace(indexed_client, trace_id, headers) if trace_id else [],
                "model_call_range": [before, len(capture.calls)],
            })
            for call in kev["calls"][kev_before:]:
                response = call["response"]["answers"]
                question = next(iter(response))
                sample["kev_choices"].append({
                    "question": question,
                    "choice": response[question].get("choice"),
                    "probabilities": response[question].get("probabilities"),
                })
            return body

        if case_id == "snack_type_first":
            session_id = support.create_session(indexed_client)
            save_turn("type_first", "来点零食", session_id)
        elif case_id == "same_category_cola_filter":
            session_id = support.create_session(indexed_client)
            shown = save_turn("compare_cola", "比较可口可乐多件装，整包不超过20元", session_id)
            selected = save_turn("select_for_plan", "选这款生成清单", session_id, shown)
            ack = save_turn("ack_plan", "好的", session_id, selected)
            save_turn("filter_same_category", "只看1元以下的可乐", session_id, ack)
            sample["cart_items_after"] = indexed_client.get("/api/v1/cart").json().get("items")
        elif case_id == "keke_return_policy":
            session_id = support.create_session(indexed_client, page="product")
            save_turn(
                "return_policy", "这个商品不喜欢能退吗", session_id,
                view_context={"page": "product", "product_id": "demo:cn-coke-zero-500ml-bottle"},
            )
        elif case_id == "momo_selected_order_return":
            import mercury.agent as mercury_agent
            import mercury.llm as mercury_llm
            from openai import OpenAI as RealOpenAI

            mercury_agent._HISTORY.clear()
            real_openai = RealOpenAI
            def captured_openai(**kwargs):
                http_client = httpx.Client(
                    transport=capture,
                    timeout=httpx.Timeout(float(settings.llm_timeout), connect=10.0),
                    trust_env=False,
                )
                return real_openai(**kwargs, http_client=http_client)
            monkeypatch.setattr(mercury_llm, "OpenAI", captured_openai)

            cart = indexed_client.post("/api/v1/cart/items", json={
                "sku_id": "demo:eggs-fresh-6pack", "quantity": 2,
                "expected_cart_version": 0,
            }).json()
            order = indexed_client.post("/api/v1/cart/checkout", json={
                "expected_cart_version": cart["version"],
            }).json()["order"]
            second_cart = indexed_client.post("/api/v1/cart/items", json={
                "sku_id": "demo:eggs-fresh-6pack", "quantity": 1,
            }).json()
            other = indexed_client.post("/api/v1/cart/checkout", json={
                "expected_cart_version": second_cart["version"],
            }).json()["order"]
            session = indexed_client.post("/api/v1/mercury/sessions").json()
            session_id = session["session_id"]
            selected = indexed_client.post(
                f"/api/v1/mercury/sessions/{session_id}/order",
                json={"order_id": order["order_id"]},
            )
            if selected.status_code != 200:
                raise RuntimeError(f"selected-order setup HTTP {selected.status_code}")
            turn_started = time.perf_counter()
            response = indexed_client.post(
                f"/api/v1/mercury/sessions/{session_id}/turns/stream",
                json={"message": "我要求退这件商品", "request_id": f"{case_id}-{uuid.uuid4().hex[:8]}"},
            )
            elapsed = round((time.perf_counter() - turn_started) * 1000, 1)
            events = []
            for line in response.text.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                events.append({
                    "event": event.get("event"),
                    "final_text": event.get("final_text"),
                    "code": event.get("code"),
                })
            sample["selected_order_setup"] = {
                "selected_order_is_new_and_case_local": selected.status_code == 200,
                "competing_order_created": bool(other.get("order_id")),
                "selected_order_status": order.get("status"),
                "item_count": len(order.get("items", [])),
            }
            sample["turns"].append({
                "label": "selected_order_return",
                "user_message": "我要求退这件商品",
                "http_status": response.status_code,
                "events": events,
                "turn_elapsed_ms": elapsed,
                "model_call_range": [0, len(capture.calls)],
                "returns_after": "no_return_record" if "未签收" in response.text else "see_events",
            })
        sample["semantic_calls"] = capture.calls
        sample["status"] = "completed"
    except Exception as exc:
        sample["semantic_calls"] = capture.calls if capture else []
        sample["status"] = "failed"
        sample["failure_type"] = type(exc).__name__
        code = getattr(exc, "code", None)
        if isinstance(code, str):
            sample["failure_code"] = code
        sample["failure_message"] = str(exc)[:300]
    finally:
        sample["sample_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        try:
            client_gen.close()
        except NameError:
            pass
        monkeypatch.undo()

    text = json.dumps(sample, ensure_ascii=False, indent=2)
    text = CREDENTIAL_VALUE.sub(r"\1[REDACTED]", text)
    out = output_dir / f"{case_id}.json"
    out.write_text(text + "\n", encoding="utf-8")
    return {"output": str(out), "status": sample["status"], "model_calls": len(sample["semantic_calls"]),
            "usage": [call.get("usage") for call in sample["semantic_calls"]],
            "sample_elapsed_ms": sample["sample_elapsed_ms"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True)
    parser.add_argument("--case", required=True, choices=[
        "snack_type_first", "same_category_cola_filter", "keke_return_policy",
        "momo_selected_order_return",
    ])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    tree = Path(args.tree).resolve()
    output_dir = Path(args.output_dir).resolve()
    result = run_case(tree, args.case, output_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

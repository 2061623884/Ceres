"""Work-only pytest observer for the frozen Ceres V3 offline suite."""

import base64
import json
import os
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient


TRACE = Path(os.environ["CERES_TRACE_PATH"])
COVERAGE_PLAN = Path(os.environ["CERES_COVERAGE_PLAN_PATH"])
CURRENT_NODE = None
WRITE_LOCK = threading.Lock()
SEND_SEQUENCE = 0
ORIGINAL_TESTCLIENT_SEND = TestClient.send


def append(record):
    with WRITE_LOCK:
        with TRACE.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _json_body(raw_body):
    if not isinstance(raw_body, bytes) or not raw_body:
        return None
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def traced_testclient_send(self, request, *args, **kwargs):
    global SEND_SEQUENCE
    SEND_SEQUENCE += 1
    sequence = SEND_SEQUENCE
    request_body = getattr(request, "_content", None)
    request_json = _json_body(request_body)
    try:
        response = ORIGINAL_TESTCLIENT_SEND(self, request, *args, **kwargs)
    except BaseException as exc:
        append({
            "kind": "testclient_send_error",
            "nodeid": CURRENT_NODE,
            "sequence": sequence,
            "method": request.method,
            "url": str(request.url),
            "request_json": request_json,
            "request_body_base64": base64.b64encode(request_body).decode("ascii")
            if isinstance(request_body, bytes) else None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise

    response_body = getattr(response, "_content", None)
    append({
        "kind": "testclient_response",
        "nodeid": CURRENT_NODE,
        "sequence": sequence,
        "method": request.method,
        "url": str(request.url),
        "request_json": request_json,
        "request_body_base64": base64.b64encode(request_body).decode("ascii")
        if isinstance(request_body, bytes) else None,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "raw_response_observed": isinstance(response_body, bytes),
        "response_body_base64": base64.b64encode(response_body).decode("ascii")
        if isinstance(response_body, bytes) else None,
    })
    return response


TestClient.send = traced_testclient_send


def _item_matches_selector(item, selector, case_id):
    selector = selector.removeprefix("backend/")
    selected_function = selector.split("::", 1)[1]
    if item.nodeid.split("[", 1)[0] != selector:
        return False

    params = getattr(getattr(item, "callspec", None), "params", {})
    if selected_function == "test_fixed_shopping_utterance_reaches_real_plan_after_required_consent":
        expected = {
            "R01": {"role": "keke", "decision": "stay_current", "quantity": 2},
            "R08": {"role": "momo", "decision": "suggest_switch", "quantity": 1},
        }.get(case_id)
        return expected is not None and all(params.get(key) == value for key, value in expected.items())
    if selected_function == "test_keke_policy_stays_and_answers_with_source":
        return params.get("case_id") == case_id
    return True


def pytest_collection_finish(session):
    collected = [item.nodeid for item in session.items]
    append({"kind": "collection_manifest", "nodeids": collected, "count": len(collected)})

    plan = json.loads(COVERAGE_PLAN.read_text(encoding="utf-8"))
    actual_by_case = {}
    for case_id, selectors in plan["mapping"].items():
        matches = []
        for selector in selectors:
            matches.extend(
                item.nodeid for item in session.items
                if _item_matches_selector(item, selector, case_id)
            )
        actual_by_case[case_id] = list(dict.fromkeys(matches))

    append({
        "kind": "core_case_node_mapping",
        "case_version": plan["case_version"],
        "case_count": plan["case_count"],
        "case_nodes": actual_by_case,
    })


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        module = item.module
        original = getattr(module, "events", None)
        if not callable(original) or getattr(original, "_ceres_trace_wrapper", False):
            continue

        def traced_events(response, _original=original):
            events = _original(response)
            append({"kind": "sse_events", "nodeid": CURRENT_NODE, "events": events})
            return events

        traced_events._ceres_trace_wrapper = True
        module.events = traced_events


def pytest_runtest_setup(item):
    global CURRENT_NODE
    CURRENT_NODE = item.nodeid
    append({"kind": "test_start", "nodeid": item.nodeid})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    append({
        "kind": "test_result",
        "nodeid": item.nodeid,
        "outcome": report.outcome,
        "duration_seconds": report.duration,
        "parameters": getattr(getattr(item, "callspec", None), "params", {}),
        "failure": str(report.longrepr) if report.failed else None,
        "captured_sections": report.sections,
    })


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    global CURRENT_NODE
    yield
    CURRENT_NODE = None

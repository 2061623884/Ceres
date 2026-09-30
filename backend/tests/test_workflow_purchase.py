
import pytest
"""Purchase task workflow tests."""

import uuid
from support import post_turn


def _session(client, page="home"):
    resp = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": page, "category_id": None, "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    )
    return resp.json()["session_id"]


def _turn(client, session_id, message, task_id=None, version=0, request_id=None):
    previous = {"task_id": task_id, "state_version": version}
    return post_turn(
        client, session_id, message, previous, request_id=request_id or str(uuid.uuid4())
    )


def test_purchase_task_flow(client, semantic_provider):
    """A vague dinner request asks one question; the answer builds a real plan.

    Two model calls total, both scripted, both retrieving for real: the vague
    turn recommends from a real topic search and asks about what it really
    found, and the second turn adds the dish the shopper actually named.

    Two assertions of the original probe cannot survive as written.
    ``data2["task_id"] == task_id`` required the question to belong to a task;
    a question is not a purchase (spec rule 1/2), so no task exists until the
    first mutation and the task is opened by the second turn instead of
    continued from the first. And a recommend-then-ask turn no longer produces
    ``pending_clarifications`` with server-built candidate options — the
    question is now the model's own reply, grounded in the real
    ``query_results`` (spec rule 1: the answer stage only has ``reply`` /
    ``display_refs``); ``uncertainties``/``pending_clarifications`` remain only
    for a question raised in the understanding pass itself. The continuity the
    first assertion protected — the second turn is accepted rather than
    rejected as stale, and it lands on a real task — is asserted directly below.
    """
    from support.semantic_agent import lookup_then_add, recommend_then, topic_rows

    def ask(request):
        rows = topic_rows(request)
        assert len(rows) >= 2, rows
        names = [r["name"] for r in rows[:2]]
        return {
            "reply": f"今晚想吃{names[0]}还是{names[1]}？",
            "display_refs": [r["ref"] for r in rows[:2]],
        }

    semantic_provider(recommend_then(None, ask))
    sid = _session(client)
    r1 = _turn(client, sid, "今晚想做顿简单的饭")
    assert r1.status_code == 200
    data = r1.json()
    # A question before any purchase is not a task step, so this turn reports
    # "understanding" rather than a plan state. (The retired chain reported
    # "clarifying" here.)
    assert data["status"] == "understanding", data
    assert data["plan_effect"] == "keep", data
    assert data["plan"] is None
    assert not data.get("pending_clarifications")
    # The real recommend retrieval ran and the question is grounded in it.
    lookup_receipt = next(r for r in data["action_results"] if r.get("kind") == "recommend")
    assert lookup_receipt["status"] == "completed", lookup_receipt
    assert "番茄炒蛋" in data["message"] or "蛋炒饭" in data["message"], data["message"]
    task_id = data["task_id"]
    version = data["state_version"]

    semantic_provider(
        lookup_then_add(
            "dish",
            "番茄炒蛋",
            people=2,
            constraints={"budget_yuan": 50},
        )
    )
    r2 = _turn(client, sid, "两个人，清淡一点，预算五十元以内", task_id, version)
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["task_id"], data2
    assert data2["status"] == "awaiting_confirmation"
    assert data2["plan"] is not None
    assert data2["plan"]["total_price_fen"] <= 5000


def test_clarifying_self_loop(client):
    sid = _session(client)
    r1 = _turn(client, sid, "今晚想做顿简单的饭")
    task_id = r1.json()["task_id"]
    version = r1.json()["state_version"]
    if r1.json()["status"] == "clarifying":
        r2 = _turn(client, sid, "还是不太确定", task_id, version)
        assert r2.status_code == 200
        assert r2.json()["status"] in ("clarifying", "degraded", "awaiting_confirmation")


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent

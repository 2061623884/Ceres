"""The turn's own budget, and the difference between a timeout and a stop.

A model call and a plan build can both take arbitrarily long, and a turn that is
still writing when its budget is spent is a turn that sells something nobody
agreed to. These tests drive the turn clock by hand — no sleeping — and check
three things:

* once the budget is spent, no further model call, read or plan change starts;
* a timeout is reported as itself, never as a shopper cancellation;
* a prepared change whose budget expires before commit preserves the existing
  plan and its versions; it cannot be reported as saved.
* a plan already committed before its SSE publication remains visible and
  replayable when the clock expires during that publication.

They run through the real HTTP entry, the real services and a temporary database.
The user's side of the race is real too: nothing here patches the executor's
checks away.
"""

from __future__ import annotations

import uuid

import pytest

from support import create_session, post_turn, stream_turn
from support.semantic_agent import (
    lookup_then_add,
    request_amend,
)


def send(client, sid, text, previous=None, request_id=None):
    previous = previous or {}
    return post_turn(client, sid, text, previous, request_id=request_id or str(uuid.uuid4()))


def send_ok(client, sid, text, previous=None, request_id=None):
    response = send(client, sid, text, previous, request_id)
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(client, sid):
    response = client.get(f"/api/v1/guide/sessions/{sid}")
    assert response.status_code == 200, response.text
    return response.json()


class _TurnClock:
    """The turn clock, moved by hand so a deadline needs no sleeping."""

    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def turn_clock(monkeypatch):
    import app.agent.turn_primitives as turn_module

    clock = _TurnClock()
    monkeypatch.setattr(turn_module, "_monotonic", clock)
    return clock


@pytest.fixture()
def turn_budget(monkeypatch):
    """A finite, positive budget, so a turn can be driven past it on purpose."""
    seconds = 30.0
    monkeypatch.setenv("SEMANTIC_TURN_TIMEOUT_SECONDS", str(seconds))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield seconds
    get_settings.cache_clear()


def _two_products(request, fragments: tuple[str, str]) -> dict:
    """Two adds in one proposal, from the refs the server really issued."""
    matches = [
        row
        for result in (request.get("query_results") or [])
        if result.get("kind") == "lookup" and result.get("status") == "completed"
        for row in (result.get("matches") or [])
    ]
    mutations = []
    for fragment in fragments:
        row = next(r for r in matches if fragment in str(r["name"]))
        mutations.append({"verb": "add", "candidate_ref": row["ref"], "name": row["name"]})
    return {"mutations": mutations}


# --------------------------------------------------------- the budget runs out


def test_a_model_that_outlives_the_budget_writes_nothing(
    client, semantic_provider, turn_clock, turn_budget
):
    """A model timeout is an SSE error; no task, plan or cart write follows."""
    def slow_round(request):
        turn_clock.now += turn_budget * 2
        return {
            "target": {"kind": "product", "name": "牛奶", "intent": "buy"},
            "lookups": [{"kind": "product", "query": "牛奶"}],
        }

    semantic_provider([slow_round])
    sid = create_session(client)
    events = stream_turn(client, sid, "买一盒牛奶")
    terminal = events[-1]
    assert terminal["type"] == "error", events
    assert terminal["payload"]["code"] == "TURN_DEADLINE_EXCEEDED", terminal
    assert terminal["payload"]["retryable"] is True, terminal
    assert snapshot(client, sid)["task_id"] is None
    assert snapshot(client, sid)["plan"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_read_that_outlives_the_budget_writes_nothing(
    client, semantic_provider, turn_clock, turn_budget, monkeypatch
):
    """A slow read carries the same deadline error without a plan write."""
    from app.agent.tools import read as read_module
    original_lookup = read_module.ReadTools._lookup

    def slow_lookup(self, lookup, candidates):
        turn_clock.now += turn_budget * 2
        return original_lookup(self, lookup, candidates)

    monkeypatch.setattr(read_module.ReadTools, "_lookup", slow_lookup)
    semantic_provider([*lookup_then_add("product", "全脂牛奶 1升")])
    sid = create_session(client)
    events = stream_turn(client, sid, "买一盒牛奶")
    terminal = events[-1]
    assert terminal["type"] == "error", events
    assert terminal["payload"]["code"] == "TURN_DEADLINE_EXCEEDED", terminal
    assert terminal["payload"]["retryable"] is True, terminal
    assert snapshot(client, sid)["task_id"] is None
    assert snapshot(client, sid)["plan"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_shopper_stop_is_a_stop_and_never_a_timeout(client, semantic_provider):
    """Signal the actual streaming request through the public stop API."""
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    def stop_during_the_call(request):
        stopped = client.post(f"/api/v1/guide/sessions/{sid}/turns/stop",
                              json={"request_id": request_id})
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["cancelled"] is True, stopped.text
        return {"reply": "已经买好了"}

    semantic_provider([stop_during_the_call])
    events = stream_turn(client, sid, "买一件牛奶", request_id=request_id)
    terminal = events[-1]
    assert terminal["type"] == "turn.stopped", events
    assert terminal["payload"]["status"] == "stopped", terminal
    assert terminal["payload"]["answer_status"] == "stopped", terminal
    assert terminal["payload"]["plan"] is None, terminal
    assert all(row.get("code") != "TURN_DEADLINE_EXCEEDED"
               for row in terminal["payload"]["action_results"])
    assert snapshot(client, sid)["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_rebuild_that_expires_before_commit_keeps_the_existing_plan(
    client, semantic_provider, turn_clock, turn_budget, monkeypatch
):
    """One current-protocol rebuild is prepared, then refused before commit."""
    from app.agent.tools.change_plan import PlanChangeExecutor
    sid = create_session(client)
    semantic_provider([*lookup_then_add("dish", "番茄炒蛋", people=2)])
    first = send_ok(client, sid, "我想自己煮番茄炒蛋，两个人")
    assert first["plan"]["items"], first
    before = snapshot(client, sid)
    cart_before = client.get("/api/v1/cart").json()
    prepared = []
    original_prepare = PlanChangeExecutor.prepare

    def expire_after_prepare(self, *args, **kwargs):
        result = original_prepare(self, *args, **kwargs)
        prepared.append(result)
        turn_clock.now += turn_budget * 2
        return result

    monkeypatch.setattr(PlanChangeExecutor, "prepare", expire_after_prepare)

    def people_change(request):
        group = request["current_plan"]["groups"][0]
        return request_amend(focus=group["ref"], name=group["name"],
                             changes={"set": {"people": 4}})

    semantic_provider([people_change])
    events = stream_turn(client, sid, "改成四个人的份量", first)
    terminal = events[-1]
    assert len(prepared) == 1, prepared
    assert terminal["type"] == "error", events
    assert terminal["payload"]["code"] == "TURN_DEADLINE_EXCEEDED", terminal
    stored = snapshot(client, sid)
    for key in ("task_id", "state_version", "session_version", "plan"):
        assert stored[key] == before[key], (key, before, stored)
    assert client.get("/api/v1/cart").json() == cart_before


def test_a_saved_plan_is_reported_when_the_budget_expires_during_publication(
    client, semantic_provider, turn_clock, turn_budget, monkeypatch
):
    """The committed plan is truth even if time runs out sending plan.ready."""
    from app.agent.turn_progress import CallbackTurnProgressSink
    sid = create_session(client)
    request_id = str(uuid.uuid4())
    original_ready = CallbackTurnProgressSink.on_plan_ready
    published = []

    def expire_after_publication(self, payload):
        original_ready(self, payload)
        published.append(payload)
        turn_clock.now += turn_budget * 2

    monkeypatch.setattr(CallbackTurnProgressSink, "on_plan_ready", expire_after_publication)
    semantic_provider([*lookup_then_add("product", "全脂牛奶 1升")])
    events = stream_turn(client, sid, "买一盒牛奶", request_id=request_id)
    terminal = events[-1]
    assert len(published) == 1, published
    assert terminal["type"] == "turn.completed", events
    body = terminal["payload"]
    ready = next(event["payload"]["plan"] for event in events if event["type"] == "plan.ready")
    assert body["committed"] is True, body
    for key in ("plan_effect", "task_id", "state_version", "session_version"):
        assert ready[key] == body[key], (key, ready, body)
    assert {key: value for key, value in ready.items()
            if key not in ("plan_effect", "task_id", "state_version", "session_version")} == body["plan"], (ready, body)
    assert body["status"] == "awaiting_confirmation", body
    assert all(row.get("code") != "TURN_DEADLINE_EXCEEDED" for row in body["action_results"]), body
    before = snapshot(client, sid)
    assert before["task_id"] == body["task_id"], before
    assert before["state_version"] == body["state_version"], before
    assert before["plan"]["plan_id"] == ready["plan_id"], before
    assert before["plan"]["plan_version"] == ready["plan_version"], before
    assert [(row["sku_id"], row["quantity"]) for row in before["plan"]["items"]] == [
        (row["sku_id"], row["quantity"]) for row in ready["items"]
    ], before
    replay = stream_turn(client, sid, "买一盒牛奶", request_id=request_id)[-1]
    assert replay["type"] == "turn.completed", replay
    assert replay["payload"]["assistant_message_id"] == body["assistant_message_id"], replay
    assert replay["payload"]["plan"] == body["plan"], replay
    assert snapshot(client, sid) == before
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_stop_that_arrives_during_the_build_writes_no_plan(
    client, semantic_provider, monkeypatch
):
    """Stop at the real SSE validation phase, preserving executor checks."""
    from app.agent.turn_progress import CallbackTurnProgressSink
    sid = create_session(client)
    request_id = str(uuid.uuid4())
    original_phase = CallbackTurnProgressSink.on_phase
    phases = []

    def on_phase(self, phase):
        original_phase(self, phase)
        phases.append(phase)
        if phase == "validate":
            stopped = client.post(f"/api/v1/guide/sessions/{sid}/turns/stop",
                                  json={"request_id": request_id})
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["cancelled"] is True, stopped.text

    monkeypatch.setattr(CallbackTurnProgressSink, "on_phase", on_phase)
    semantic_provider([*lookup_then_add("product", "全脂牛奶 1升")])
    events = stream_turn(client, sid, "买一盒牛奶", request_id=request_id)
    terminal = events[-1]
    assert "validate" in phases, phases
    assert terminal["type"] == "turn.stopped", events
    body = terminal["payload"]
    assert body["task_id"] is None, body
    assert body["plan"] is None, body
    codes = [row.get("code") for row in body["action_results"]]
    assert "STOPPED" in codes, body
    assert "TURN_DEADLINE_EXCEEDED" not in codes, body
    assert body["status"] == "stopped", body
    assert body["answer_status"] == "stopped", body
    assert snapshot(client, sid)["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


# ------------------------------------------------------------- the read port


def test_a_read_port_serves_the_first_read_and_skips_the_rest_once_time_is_up():
    """No database: the reads are faked, only the budget boundary is real."""
    from app.agent.protocol import CandidateSet, parse_proposal
    from app.agent.tools.read import REASON_DEADLINE, STATUS_COMPLETED, STATUS_SKIPPED, ReadTools

    served: list[str] = []

    class _CountingReads(ReadTools):
        def _lookup(self, lookup, candidates):
            served.append(f"lookup:{lookup.query}")
            return {
                "kind": "lookup",
                "lookup_kind": lookup.kind,
                "query": lookup.query,
                "status": STATUS_COMPLETED,
                "matches": [],
            }

        def _query(self, query, candidates):
            served.append(f"query:{query.kind}")
            return {"kind": query.kind, "status": STATUS_COMPLETED}

    # The budget is spent by the time the first read has finished.
    reads = _CountingReads(
        None,
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
        deadline_expired=lambda: len(served) >= 1,
    )

    proposal = parse_proposal({
        "lookups": [
            {"kind": "product", "query": "牛奶"},
            {"kind": "product", "query": "可乐"},
        ],
        "reads": [{"kind": "recommend"}],
    })

    results = reads.serve(proposal, CandidateSet(), lookup_limit=2)

    assert [r["status"] for r in results] == [
        STATUS_COMPLETED, STATUS_SKIPPED, STATUS_SKIPPED
    ]
    assert results[1]["reason"] == REASON_DEADLINE
    assert results[2]["reason"] == REASON_DEADLINE
    assert served == ["lookup:牛奶"], "no later read may start after the budget is spent"


def test_a_read_port_out_of_time_serves_nothing_and_reports_every_request():
    """Between two reads the budget is checked; no request is silently dropped."""
    from app.agent.protocol import CandidateSet, parse_proposal
    from app.agent.tools.read import REASON_DEADLINE, STATUS_SKIPPED, ReadTools

    proposal = parse_proposal({
        "lookups": [
            {"kind": "product", "query": "牛奶"},
            {"kind": "product", "query": "可乐"},
        ],
        "reads": [{"kind": "recommend"}],
    })
    # ``db`` is never touched: the budget is checked before the first read.
    reads = ReadTools(
        None,
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
        deadline_expired=lambda: True,
    )

    results = reads.serve(proposal, CandidateSet(), lookup_limit=2)

    assert [r["status"] for r in results] == [STATUS_SKIPPED] * 3
    assert {r["reason"] for r in results} == {REASON_DEADLINE}
    assert results[0]["lookup_kind"] == "product"
    assert results[0]["matches"] == []
    assert results[2]["kind"] == "recommend"

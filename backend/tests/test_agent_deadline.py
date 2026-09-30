"""The turn's own budget, and the difference between a timeout and a stop.

A model call and a plan build can both take arbitrarily long, and a turn that is
still writing when its budget is spent is a turn that sells something nobody
agreed to. These tests drive the turn clock by hand — no sleeping — and check
three things:

* once the budget is spent, no further model call, read or plan change starts;
* a timeout is reported as itself, never as a shopper cancellation;
* a mutation that *did* commit before the budget ran out is reported as saved,
  with its plan, and is never presented as a full rollback.

They run through the real HTTP entry, the real services and a temporary database.
The user's side of the race is real too: nothing here patches the executor's
checks away.
"""

from __future__ import annotations

import uuid

import pytest

from support import create_session, post_turn
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
    """The call itself is slower than the whole turn: no task, no plan, no cart.

    A turn with nothing committed fails through the ordinary failure path — the
    same one a model failure takes — with its own code and ``retryable``, so the
    trace and the SSE error agree.
    """

    def slow_round(request):
        turn_clock.now += turn_budget * 2
        return {
            "target": {"kind": "product", "name": "牛奶", "intent": "buy"},
            "lookups": [{"kind": "product", "query": "牛奶"}],
        }

    semantic_provider([slow_round])
    sid = create_session(client)

    response = send(client, sid, "买一盒牛奶")

    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "TURN_DEADLINE_EXCEEDED", error
    assert error["retryable"] is True, error
    # Nothing was created behind the failure, and the cart is untouched.
    assert snapshot(client, sid)["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_read_that_outlives_the_budget_writes_nothing(
    client, semantic_provider, turn_clock, turn_budget, monkeypatch
):
    """A slow read, not a slow model: the same refusal, with real services."""
    from app.agent.tools import read as read_module

    original_lookup = read_module.ReadTools._lookup

    def slow_lookup(self, lookup, candidates):
        turn_clock.now += turn_budget * 2
        return original_lookup(self, lookup, candidates)

    monkeypatch.setattr(read_module.ReadTools, "_lookup", slow_lookup)

    semantic_provider([*lookup_then_add("product", "全脂牛奶 1升")])
    sid = create_session(client)

    response = send(client, sid, "买一盒牛奶")

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "TURN_DEADLINE_EXCEEDED", response.text
    # The read really ran, but the plan change it was for did not.
    assert snapshot(client, sid)["task_id"] is None
    assert snapshot(client, sid)["plan"] is None
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_shopper_stop_is_a_stop_and_never_a_timeout(
    client, semantic_provider, monkeypatch
):
    """The two are different facts about a turn, and the client can tell them apart."""
    from app.agent.turn_progress import NoOpTurnProgressSink

    stopped = {"value": False}
    monkeypatch.setattr(
        NoOpTurnProgressSink, "should_stop", lambda self: stopped["value"]
    )

    def stop_during_the_call(request):
        stopped["value"] = True
        return {"reply": "已经买好了"}

    semantic_provider([stop_during_the_call])
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    body = send_ok(client, sid, "买一件牛奶", None, request_id)

    assert body["status"] == "stopped"
    assert body["message"] == "已停止，原清单保持不变。"
    assert body["plan"] is None
    assert all(
        r.get("code") != "TURN_DEADLINE_EXCEEDED" for r in body["action_results"]
    )


def test_a_mutation_committed_before_the_budget_runs_out_is_reported_as_saved(
    client, semantic_provider, turn_clock, turn_budget, monkeypatch
):
    """A plan, then two headcount rebuilds where only the first fits the budget.

    Two supplements of the *same* goal are one turn's work: the first rebuild
    commits, and the second one is what consumes the remaining budget — so the
    refusal happens after that mutation has started, the case a check placed
    before the whole execution would miss.
    """
    from app.agent.turn_progress import NoOpTurnProgressSink

    armed = {"value": False}
    validates = {"n": 0}
    original_phase = NoOpTurnProgressSink.on_phase

    def on_phase(self, phase):
        original_phase(self, phase)
        if phase != "validate" or not armed["value"]:
            return
        validates["n"] += 1
        if validates["n"] == 2:
            # The second rebuild is what the budget runs out during.
            turn_clock.now += turn_budget * 2

    monkeypatch.setattr(NoOpTurnProgressSink, "on_phase", on_phase)

    def two_people_changes(request):
        """A headcount supplement of the goal on screen (four people)."""
        group = request["current_plan"]["groups"][0]
        return request_amend(
            focus=group["ref"], name=group["name"], changes={"set": {"people": 4}}
        )

    sid = create_session(client)
    semantic_provider([*lookup_then_add("dish", "番茄炒蛋", "番茄", people=2)])
    first = send_ok(client, sid, "我想自己煮番茄炒蛋，两个人", None)
    assert first["plan"]["items"]

    armed["value"] = True
    semantic_provider([two_people_changes])
    body = send_ok(client, sid, "改成四个人的份量，再改成三个人", first)

    # A spent budget is not a purchase step: the turn itself is reported failed,
    # while the step stays a legal one because a plan really is awaiting a decision.
    assert body["status"] != "stopped"
    assert body["answer_status"] == "failed"
    assert body["purchase_step"] == "awaiting_confirmation"
    committed = [r for r in body["action_results"] if r.get("status") == "committed"]
    timed_out = [
        r for r in body["action_results"] if r.get("code") == "TURN_DEADLINE_EXCEEDED"
    ]
    assert len(committed) == 1, body["action_results"]
    assert len(timed_out) == 1, body["action_results"]

    # The part that really was saved is reported as saved — not as a rollback —
    # and the plan that exists is delivered with it.
    assert "已经保存的部分" in body["message"]
    assert body["plan"] is not None
    assert body["plan"]["targets"][0]["people"] == 4, body["plan"]["targets"]

    # The response agrees with the database, and the refused mutation advanced
    # nothing: no phantom plan and no phantom version.
    stored = snapshot(client, sid)
    assert stored["plan"]["targets"][0]["people"] == 4, stored["plan"]["targets"]
    assert body["state_version"] == first["state_version"] + 1
    assert stored["state_version"] == body["state_version"]


def test_a_stop_that_arrives_during_the_build_writes_no_plan(
    client, semantic_provider, monkeypatch
):
    """The cancellation lands while the mutation is being prepared."""
    from app.agent.turn_progress import NoOpTurnProgressSink

    stopped = {"value": False}
    original_phase = NoOpTurnProgressSink.on_phase

    def on_phase(self, phase):
        original_phase(self, phase)
        if phase == "validate":
            stopped["value"] = True

    monkeypatch.setattr(NoOpTurnProgressSink, "on_phase", on_phase)
    monkeypatch.setattr(
        NoOpTurnProgressSink, "should_stop", lambda self: stopped["value"]
    )

    semantic_provider([*lookup_then_add("product", "全脂牛奶 1升")])
    sid = create_session(client)
    request_id = str(uuid.uuid4())

    body = send_ok(client, sid, "买一盒牛奶", None, request_id)

    assert body["task_id"] is None
    assert body["plan"] is None
    codes = [r.get("code") for r in body["action_results"]]
    assert "STOPPED" in codes
    assert "TURN_DEADLINE_EXCEEDED" not in codes
    # A stop that arrives while a plan is being built is a stopped generation, not
    # a completed turn, and never a shopper-cancelled *task*.
    assert body["status"] == "stopped"
    assert body["answer_status"] == "stopped"
    # A refused mutation leaves no half-built task behind.
    assert snapshot(client, sid)["task_id"] is None


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

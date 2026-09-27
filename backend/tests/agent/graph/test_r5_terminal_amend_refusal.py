"""R5 regression: an amend of a settled task is refused, not silently rebuilt.

The legacy executor checks "a confirmed task's history is immutable" *before* it
rebuilds a ``change people`` group through the add path. The graph's pure
``PlanChangeExecutor.prepare`` did the rebuild first, so an amend on a terminal
task could open a second purchase task and replace the plan instead of refusing.

This test drives the real HTTP entry (the graph service) and asserts both the
structured refusal and the untouched business counters. It does not patch any
production rule away.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core import database
from support import create_session, post_turn
from support.semantic_agent import request_new, request_amend

TOMATO = "番茄炒蛋"


def _turn(client, sid: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(
        client,
        sid,
        message,
        previous,
        request_id=str(uuid.uuid4()),
    )


def _counts(session_id: str) -> tuple[int, int, int]:
    db = database.SessionLocal()
    try:
        tasks = db.execute(
            text("SELECT COUNT(*) FROM guide_tasks WHERE session_id = :s"), {"s": session_id}
        ).scalar_one()
        snapshots = db.execute(
            text("SELECT COUNT(*) FROM plan_snapshots WHERE session_id = :s"),
            {"s": session_id},
        ).scalar_one()
        messages = db.execute(
            text("SELECT COUNT(*) FROM guide_messages WHERE session_id = :s"),
            {"s": session_id},
        ).scalar_one()
        return int(tasks), int(snapshots), int(messages)
    finally:
        db.close()


def test_amending_a_settled_task_is_refused_not_rebuilt(client, semantic_provider):
    sid = create_session(client)
    semantic_provider([{
        "understanding": request_new("dish", TOMATO, people=2),
        "lookups": [{"kind": "dish", "query": TOMATO}],
    }])
    first = _turn(client, sid, "我想吃番茄炒蛋，两个人").json()
    assert first["plan"] and first["task_id"], first

    db = database.SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE guide_tasks SET status = 'completed', current_step = 'completed' "
                "WHERE task_id = :t"
            ),
            {"t": first["task_id"]},
        )
        db.commit()
    finally:
        db.close()

    before = _counts(sid)

    def amend(request):
        group = request["current_plan"]["groups"][0]
        return {
            "reply": "改成三个人的份量。",
            "understanding": request_amend(focus=group["ref"]),
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": group["ref"],
                    "name": group["name"],
                    "field": "people",
                    "people": 3,
                }
            ],
        }

    semantic_provider([amend])
    second = _turn(
        client,
        sid,
        "改成三个人的份量",
        {
            "task_id": first["task_id"],
            "state_version": first["state_version"],
            "session_version": first["session_version"],
        },
    ).json()

    codes = {row.get("code") for row in second.get("action_results") or []}
    assert "TASK_COMPLETED_READ_ONLY" in codes, second
    assert second["plan_effect"] == "keep", second
    assert second["plan"] is None, second
    assert second["session_version"] == first["session_version"], second

    after = _counts(sid)
    # The refusal writes this turn's user/assistant messages but no new task, no
    # plan snapshot and no plan: the settled task's history stays immutable.
    assert after[0] == before[0], (before, after)
    assert after[1] == before[1], (before, after)
    assert after[2] == before[2] + 2, (before, after)
    db = database.SessionLocal()
    try:
        status = db.execute(
            text("SELECT status FROM guide_tasks WHERE task_id = :t"), {"t": first["task_id"]}
        ).scalar_one()
        assert status == "completed"
    finally:
        db.close()

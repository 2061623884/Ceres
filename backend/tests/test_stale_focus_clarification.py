"""A clarification must not outlive its own answer.

Observed: a successful add showed its receipt with a stale
"你是在说清单里的哪一项？" chip still attached. The gate had no candidate to bind
that question to, so it carried ``candidate_ref = None``; the resolve comparison
matches on a candidate ref, and the candidate-changed purge keeps exactly the
unbound items, so nothing could ever close it.
"""
from __future__ import annotations

from app.agent.protocol import CandidateSet, SemanticProposal
from app.agent.turn_context_plan import plan_context_writes


def _plan(context: dict, action_results: list[dict]):
    return plan_context_writes(
        context=context,
        session=type("S", (), {"current_task_id": "task-1"})(),
        proposal=SemanticProposal(),
        candidates=CandidateSet(),
        decision=None,
        state=None,
        previous_task_id="task-1",
        action_results=action_results,
    )


def _question(candidate_ref, *, question_id="q-focus", slot="focus"):
    return {
        "question_id": question_id,
        "question": "你是在说清单里的哪一项？可以说一下目标或商品名。",
        "slot": slot,
        "options": [{"id": "goal-old", "label": "葱花炒蛋"}],
        "candidates": [{"kind": "focus", "target_id": "goal-old", "ref": "goal-old"}],
        "candidate_ref": candidate_ref,
    }


_ADDED = [{"status": "committed", "verb": "add", "candidate_ref": "sku-1"}]


def test_an_unbound_focus_question_does_not_outlive_a_committed_add():
    """An add decides which item was meant, however the shopper phrased it."""
    plan = _plan({"pending_clarifications": [_question(None)]}, _ADDED)

    assert "q-focus" in plan.resolved
    assert plan.pending == []


def test_an_unanswered_focus_question_survives_a_turn_that_adds_nothing():
    """Only a committed add answers it: a turn that writes nothing must not
    swallow the question the shopper still has to answer."""
    plan = _plan({"pending_clarifications": [_question(None)]}, [])

    assert "q-focus" not in plan.resolved
    assert [p["question_id"] for p in plan.pending] == ["q-focus"]


def test_a_non_focus_question_is_not_closed_by_an_unrelated_add():
    """"几个人吃？" is not answered by adding something. Only focus is decided
    by the add itself."""
    people = _question(None, question_id="q-people", slot="people")

    plan = _plan({"pending_clarifications": [people]}, _ADDED)

    assert "q-people" not in plan.resolved
    assert [p["question_id"] for p in plan.pending] == ["q-people"]

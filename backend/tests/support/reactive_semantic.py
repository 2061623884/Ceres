"""Test-only model stand-in for the one semantic decision chain.

This replaces the retired tool-call scripted provider. It is **not** a product
route and it proves nothing about model quality: it is a deterministic stand-in
so the *server* side — loop → read port → executor → business services → API/SSE
— can be exercised end to end with no network and no credentials.

What it does, in the real protocol:

* model call 1 — ask for a real dish lookup, using the raw message as the query,
  and declare purchase intent;
* model call 2 — with the *real* retrieval results in hand, add the row the
  lookup actually returned, or answer when it returned nothing usable.

The one piece of language it reads is a stated headcount, so that a
constraint-only follow-up on a plan already on screen can be expressed as a real
``change … field=people``. That reading is the *test double standing in for the
model*, never a server-side rule: nothing in the runtime parses the sentence.

A test that needs an exact shape — a specific refusal, a clarification, a
particular product, an error — must script the proposals explicitly through the
``semantic_provider`` fixture. This provider is only the generic default.
"""

from __future__ import annotations

import re
from typing import Any

from app.llm.errors import LLMProviderError

#: The headcount this stand-in states when the message does not name one. It is
#: the *test double* saying a number, standing in for the model: the server may not
#: invent one, so a fixture that wants a dish plan has to state it.
DEFAULT_PEOPLE = 2

_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

#: A headcount the shopper stated ("2人", "两个人", "四人份").
_PEOPLE = re.compile(r"([一二两三四五六七八九十0-9]+)\s*(?:人|个人|人份|人吃)")

#: An explicit replacement of the target on screen ("改做…", "换成…").
#: The runtime refuses a whole-plan replacement that was not declared as a
#: ``switch``, so a stand-in that means "replace" must say so; it may not leave
#: that reading to the server. Only a *named replacement* counts: a bare
#: cancellation or negation ("取消", "不做番茄炒蛋了") has no new target and must
#: never be turned into one — the stand-in answers instead of switching.
_SWITCH = re.compile(r"改做|换成|改为|换个")


def stated_people(message: str) -> int | None:
    """The headcount the message states, for the test double only."""
    match = _PEOPLE.search(message or "")
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


def provider_error(code: str = "MODEL_TIMEOUT", retryable: bool = True) -> LLMProviderError:
    """A provider failure for scripts that need the error path."""
    return LLMProviderError(code, "scripted provider failure", retryable=retryable)


class ReactiveSemanticProvider:
    """Retrieve for real, then use what really came back. Or answer."""

    def __init__(self, *, answer: str = "好的，我来看看。", default_people: int = 2):
        self.answer = answer
        self.default_people = default_people
        #: Every request the loop really sent, in order.
        self.requests: list[dict[str, Any]] = []

    def supports_streaming(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    def remaining(self) -> int:
        """No script to exhaust: this provider answers for as long as it is asked."""
        return 0

    def propose(
        self,
        request: dict[str, Any],
        *,
        on_reply_delta=None,
        reset_stream: bool = False,
    ) -> dict[str, Any]:
        if reset_stream and on_reply_delta is not None:
            on_reply_delta("", False, True)
        self.requests.append(request)
        results = [
            result
            for result in request.get("query_results") or []
            if result.get("status") == "completed"
        ]
        change = self._plan_change(request)
        if results:
            result = self._after_retrieval(request, results)
        elif change is not None:
            result = change
        else:
            result = self._retrieve(request)
        if on_reply_delta is not None and isinstance(result, dict):
            reply = result.get("reply")
            if isinstance(reply, str) and reply:
                on_reply_delta(reply, False, False)
        return result

    # ------------------------------------------------------------- model calls

    def _retrieve(self, request: dict[str, Any]) -> dict[str, Any]:
        """Ask for real dish candidates and declare purchase intent."""
        message = str(request.get("user_message") or "")
        return {
            "lookups": [{"kind": "dish", "query": message}],
            "purchase_requested": True,
            # The stand-in declares what it is doing: a request for action. The
            # real goal (with the ref the lookup returns) follows on the second
            # call; the server derives permission from this, not from the flag.
            "understanding": {"speech_act": "request_action"},
        }

    def _after_retrieval(
        self, request: dict[str, Any], results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Add the dish the lookup really returned, or answer honestly."""
        message = str(request.get("user_message") or "")
        plan_on_screen = bool(request.get("current_plan"))
        if plan_on_screen and _SWITCH.search(message):
            relation = "switch"
        else:
            relation = "append" if plan_on_screen else "new"
        rows: list[dict[str, Any]] = []
        for result in results:
            if result.get("kind") == "lookup" and result.get("lookup_kind") == "dish":
                rows = list(result.get("matches") or [])
        picked = self._pick(rows, message)
        if picked is None:
            return {"reply": self.answer}
        mutation: dict[str, Any] = {
            "verb": "add",
            "candidate_ref": picked["ref"],
            "name": picked["name"],
        }
        people = stated_people(message) or self.default_people
        mutation["people"] = people
        return {
            "understanding": {
                "speech_act": "request_action",
                "goal_relation": relation,
                "new_goal": {
                    "kind": "meal_plan",
                    "fulfillment_mode": "self_cook",
                    "target_name": str(picked["name"]),
                    "constraints": {"people": people},
                },
            },
            "mutations": [mutation],
        }

    def _plan_change(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """A stated headcount on a plan already on screen rescales its group."""
        plan = request.get("current_plan") or {}
        groups = list(plan.get("groups") or [])
        if not groups:
            return None
        message = str(request.get("user_message") or "")
        people = stated_people(message)
        if people is None:
            return None
        requirements = request.get("requirements") or {}
        if people == requirements.get("people"):
            return None
        group = groups[0]
        return {
            "purchase_requested": True,
            "understanding": {
                "speech_act": "correct",
                "goal_relation": "amend",
                "focus_ref": group["ref"],
                "changes": {"set": {"people": people}},
            },
            "mutations": [
                {
                    "verb": "change",
                    "target_ref": group["ref"],
                    "name": str(group.get("name") or ""),
                    "field": "people",
                    "people": people,
                }
            ],
        }

    @staticmethod
    def _pick(rows: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
        """The row the shopper actually named — never "the closest one".

        A single retrieval hit is unambiguous. Several hits are only usable when
        the message really contains one of the names; otherwise the turn answers
        instead of guessing, exactly as the product must.
        """
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]
        for row in rows:
            name = str(row.get("name") or "")
            if name and name in message:
                return row
        return None


__all__ = ["ReactiveSemanticProvider", "provider_error", "stated_people"]

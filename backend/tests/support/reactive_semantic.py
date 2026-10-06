"""Test-only model stand-in for the one semantic decision chain.

It is **not** a product route and proves nothing about model quality: it is a
deterministic stand-in so the *server* side — gate → read port → executor →
business services → API/SSE — can be exercised end to end with no network and
no credentials.

What it does, in the real one-pass protocol:

* a stated headcount on a plan already on screen → ``focus`` on its first group
  plus ``constraints.people``;
* a purchase phrasing → the dish the message names as a *buy* target, with a
  lookup of that name; the server binds the exact hit the lookup returns;
* anything else that names a dish → look it up and answer from the result;
* the answer stage (``query_results`` present) → a plain reply.

The language it reads (a headcount, a replacement phrase, a dish name) is the
*test double standing in for the model*, never a server-side rule. A test that
needs an exact shape scripts it through the ``semantic_provider`` fixture.
"""

from __future__ import annotations

import re
from typing import Any

from app.llm.errors import LLMProviderError

#: The headcount this stand-in states when the message does not name one — the
#: *test double* saying a number, standing in for the model.
DEFAULT_PEOPLE = 2

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

#: A headcount the shopper stated ("2人", "两个人", "四人份").
_PEOPLE = re.compile(r"([一二两三四五六七八九十0-9]+)\s*(?:人份|人吃|个人|人)")

#: An explicit replacement of the target on screen ("改做…", "换成…"). Only a
#: *named* replacement counts; a bare cancellation never becomes a new target.
_SWITCH = re.compile(r"改做|换成|改为|换个")

#: A phrasing that asks for a list, as opposed to only asking about a dish.
_BUY = re.compile(r"想|要|买|做|吃|准备|来一|帮我|给我|改为|换")
#: A question about a dish ("番茄炒蛋怎么做"): it is looked up, never bought.
_ASK = re.compile(r"怎么|如何|有没有|吗[？?]?$")

#: Words around a dish name in the phrasings the suites use. Longer words first.
_FILLER = re.compile(
    r"我想|想要|我要|帮我|给我|今晚|今天|准备|来一份|来个|做一份|做个|改做|换成|改为|换个"
    r"|的食材|的材料|食材|材料|一下|吃|买|做"
)
_CLAUSE = re.compile(r"[，,。.!！?？；;、\s]+")
#: A clause that is a condition or a cancellation, never a dish name.
_NOT_A_NAME = re.compile(r"(不|别|预算|取消|算了|[0-9一二两三四五六七八九十]+\s*(?:元|块))")


def stated_people(message: str) -> int | None:
    """The headcount the message states, for the test double only."""
    match = _PEOPLE.search(message or "")
    if not match:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else _CN_NUM.get(token)


def dish_name(message: str) -> str:
    """The dish the message names, for the test double only (``""`` when none)."""
    for clause in _CLAUSE.split(message or ""):
        asked = next((part for part in _ASK.split(clause) if part.strip()), "")
        clause = _PEOPLE.sub("", asked).strip()
        if not clause or _NOT_A_NAME.match(clause):
            continue
        name = _FILLER.sub("", clause).strip("了的 ")
        if name:
            return name
    return ""


def provider_error(code: str = "MODEL_TIMEOUT", retryable: bool = True) -> LLMProviderError:
    """A provider failure for scripts that need the error path."""
    return LLMProviderError(code, "scripted provider failure", retryable=retryable)


class ReactiveSemanticProvider:
    """Name what the message asks for and let the server find it. Or answer."""

    def __init__(self, *, answer: str = "好的，我来看看。", default_people: int = DEFAULT_PEOPLE):
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
        if request.get("query_results"):
            # The answer stage only puts the real facts into words.
            result: dict[str, Any] = {"reply": self.answer, "display_refs": []}
        else:
            result = self._plan_change(request) or self._understand(request)
        if on_reply_delta is not None and result.get("reply"):
            on_reply_delta(result["reply"], False, False)
        return result

    def _understand(self, request: dict[str, Any]) -> dict[str, Any]:
        message = str(request.get("user_message") or "")
        name = dish_name(message)
        if not name:
            return {"reply": self.answer}
        lookups = [{"kind": "dish", "query": name}]
        if _ASK.search(message) or not (_BUY.search(message) or stated_people(message)):
            return {"target": {"kind": "meal", "name": name, "intent": "explore"}, "lookups": lookups}
        on_screen = bool(request.get("current_plan"))
        if on_screen and _SWITCH.search(message):
            relation = "replace"
        else:
            relation = "add" if on_screen else "unstated"
        return {
            "target": {"kind": "meal", "name": name, "intent": "buy", "relation": relation},
            "constraints": {
                "people": stated_people(message) or self.default_people,
                "fulfillment_mode": "self_cook",
            },
            "lookups": lookups,
        }

    @staticmethod
    def _plan_change(request: dict[str, Any]) -> dict[str, Any] | None:
        """A new headcount on a plan already on screen rescales its first group."""
        groups = list((request.get("current_plan") or {}).get("groups") or [])
        people = stated_people(str(request.get("user_message") or ""))
        if not groups or people is None:
            return None
        if people == (request.get("requirements") or {}).get("people"):
            return None
        group = groups[0]
        return {
            "focus": {"ref": group["ref"], "name": str(group.get("name") or "")},
            "constraints": {"people": people},
        }


__all__ = ["DEFAULT_PEOPLE", "ReactiveSemanticProvider", "dish_name", "provider_error", "stated_people"]

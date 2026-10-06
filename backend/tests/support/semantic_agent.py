"""Offline test double for the semantic proposal protocol.

The product still requires a live provider; this only removes the network from
the semantic loop so the protocol, the gate and the persistence can be exercised
deterministically. The builders speak the one-pass wire protocol of
``app.agent.protocol``: a proposal names the target and the reads it needs, and
the server binds the real candidate.
"""

from __future__ import annotations

from typing import Any, Callable

from app.llm.errors import LLMProviderError

from support.reactive_semantic import stated_people

Proposal = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | Exception


class Continuation:
    """The answer-stage call of the same turn: it waits for real retrieval.

    A ``Continuation`` is only handed over once the turn really carries
    ``query_results``, so "look up, then answer from what came back" can never be
    consumed by a *later* user turn — the mismatch fails loudly.
    """

    def __init__(self, build: Callable[[dict[str, Any]], dict[str, Any]]):
        self.build = build


class ScriptedSemanticProvider:
    """Returns the scripted proposal for each propose step, in order.

    A proposal may be a dict, a callable taking the request (refs known only at
    call time), an exception instance to raise, or a ``Continuation``.
    """

    def __init__(self, proposals: list[Proposal], *, name: str = "scripted-semantic"):
        self.proposals = list(proposals)
        self.name = name
        self.requests: list[dict[str, Any]] = []

    def supports_streaming(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return False

    def remaining(self) -> int:
        return len(self.proposals)

    def propose(
        self,
        request: dict[str, Any],
        *,
        on_reply_delta: Callable[[str, bool, bool], None] | None = None,
        reset_stream: bool = False,
    ) -> dict[str, Any]:
        if reset_stream and on_reply_delta is not None:
            on_reply_delta("", False, True)
        self.requests.append(request)
        if not self.proposals:
            raise LLMProviderError("EMPTY_MODEL_RESPONSE", "脚本用尽：没有更多提案", retryable=True)
        item = self.proposals[0]
        if isinstance(item, Continuation) and not request.get("query_results"):
            raise AssertionError(
                "脚本的下一步在等待检索回灌，但这一轮没有 query_results："
                "说明上一轮的检索脚本没有被消费（多步脚本与实际模型调用数不一致）"
            )
        self.proposals.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Continuation):
            result = item.build(request)
        else:
            result = item(request) if callable(item) else item
        if request.get("query_results"):
            # Scripted replies with no displayed candidates still follow the
            # answer-stage contract.
            result = {"display_refs": [], **result}
        reply = result.get("reply") if isinstance(result, dict) else None
        if on_reply_delta is not None and isinstance(reply, str) and reply:
            on_reply_delta(reply, False, False)
        return result


# --------------------------------------------------------------------- builders
#
# The suites keep their own vocabulary (dish / scenario, new / append / switch);
# these maps translate it into the wire protocol.

_KIND = {"dish": "meal", "scenario": "meal"}
_RELATION = {"new": "unstated", "append": "add", "switch": "replace"}


def candidates_of(request: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The candidate rows of one kind from a propose request."""
    key = {"dish": "dishes", "product": "products", "scenario": "scenarios"}[kind]
    return list((request.get("candidates") or {}).get(key) or [])


def request_new(
    kind: str,
    name: str,
    *,
    relation: str = "new",
    people: int | None = None,
    mode: str = "unspecified",
    items: list[str] | None = None,
    ref: str | None = None,
    quantity: int | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A proposal that asks for a list of this target ("start / add / switch to it")."""
    target: dict[str, Any] = {
        "kind": _KIND.get(kind, kind),
        "name": name,
        "intent": "buy",
        "relation": _RELATION.get(relation, relation),
    }
    if ref:
        target["ref"] = ref
    if items is not None:
        target["items"] = list(items)
    if quantity:
        target["quantity"] = quantity
    stated = dict(constraints or {})
    if people:
        stated["people"] = people
    if mode not in ("unspecified", "none"):
        stated["fulfillment_mode"] = mode
    return {"target": target, **({"constraints": stated} if stated else {})}


def request_amend(
    *,
    focus: str | None = None,
    name: str = "",
    changes: dict[str, Any] | None = None,
    op: str = "none",
    quantity: int | None = None,
) -> dict[str, Any]:
    """A proposal that acts on the thing the shopper points at.

    ``changes`` keeps the familiar ``{"set": {...}, "clear": [...]}`` shape and
    becomes ``constraints`` (a flavour word becomes ``unsupported``); ``op`` and
    ``quantity`` become a row ``edit`` on the focus.
    """
    proposal: dict[str, Any] = {}
    if focus is not None:
        proposal["focus"] = {"ref": focus, "name": name}
    changes = changes or {}
    stated = {k: v for k, v in (changes.get("set") or {}).items() if v != "unspecified"}
    if "dietary" in stated:
        stated["unsupported"] = stated.pop("dietary")
    if changes.get("clear"):
        stated["clear"] = list(changes["clear"])
    if stated:
        proposal["constraints"] = stated
    if op != "none":
        proposal["edit"] = {"op": op, **({"quantity": quantity} if quantity is not None else {})}
    return proposal


def pick(
    kind: str,
    row: dict[str, Any],
    *,
    request: dict[str, Any] | None = None,
    relation: str = "new",
    people: int | None = None,
    **modifiers: Any,
) -> dict[str, Any]:
    """Pick one server candidate by its ref: the one-pass "add this".

    A meal is generated per person, so the headcount is the one the shopper
    stated — this message, else the session's saved one — never an invented default.
    """
    if people is None and kind in ("dish", "scenario") and request is not None:
        people = stated_people(str(request.get("user_message") or "")) or (
            (request.get("requirements") or {}).get("people")
        )
    return request_new(
        kind, str(row.get("name") or ""), relation=relation, people=people,
        ref=row.get("ref"), **modifiers,
    )


def add_first(kind: str, **modifiers: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Pick the first candidate of ``kind``; refs are resolved at call time."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, kind)
        assert rows, f"没有可用的 {kind} 候选"
        return pick(kind, rows[0], request=request, **modifiers)

    return build


def add_named(
    kind: str, name_fragment: str, **modifiers: Any
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Pick the candidate whose display name contains ``name_fragment``."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, kind)
        for row in rows:
            if name_fragment in str(row.get("name") or ""):
                return pick(kind, row, request=request, **modifiers)
        raise AssertionError(f"候选清单里没有名称含「{name_fragment}」的 {kind}: {rows}")

    return build


def add_dish_preferring(
    name_fragment: str, **modifiers: Any
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Pick a dish candidate, preferring one whose name contains the fragment."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, "dish")
        assert rows, "没有可用的 dish 候选"
        chosen = next((r for r in rows if name_fragment in str(r.get("name") or "")), rows[0])
        return pick("dish", chosen, request=request, **modifiers)

    return build


def reply_only(text: str) -> dict[str, Any]:
    return {"reply": text}


def empty_proposal() -> dict[str, Any]:
    return {}


# ---------------------------------------------------------------- one-pass reads
#
# A write names its target and the lookup it needs in the *same* proposal; the
# server binds the exact hit the lookup returns (a similar hit is offered, never
# built). The only second model call of a turn is the answer stage, which puts
# real ``query_results`` into words — a script never pretends a product was
# already retrieved.


def lookup_then_add(
    kind: str,
    query: str,
    name_fragment: str | None = None,
    *,
    purchase: bool = True,
    **modifiers: Any,
) -> list[Proposal]:
    """Name the target and look it up, in one model call.

    ``name_fragment`` is the name the shopper used when it differs from the
    lookup query. Without ``purchase`` the turn only looks, so its answer stage
    is scripted as well.
    """
    lookups = [{"kind": kind, "query": query}]
    name = name_fragment or query
    if not purchase:
        target = {"kind": _KIND.get(kind, kind), "name": name, "intent": "explore"}
        return [{"target": target, "lookups": lookups}, Continuation(lambda _r: {"reply": "好的。"})]

    def build(request: dict[str, Any]) -> dict[str, Any]:
        return {**pick(kind, {"name": name}, request=request, **modifiers), "lookups": lookups}

    return [build]


def lookup_then_add_id(
    kind: str,
    query: str,
    target_id: str,
    *,
    purchase: bool = True,
    **modifiers: Any,
) -> list[Proposal]:
    """``lookup_then_add`` for a test that names the business id it expects bound.

    A proposal cannot carry ``target_id`` (ids are server-owned), so the test
    asserts it on the result instead.
    """
    return lookup_then_add(kind, query, purchase=purchase, **modifiers)


def lookup_then(
    kind: str, query: str, build: Callable[[dict[str, Any]], dict[str, Any]]
) -> list[Proposal]:
    """Look up for real, then answer from the result (the answer stage)."""
    return [{"lookups": [{"kind": kind, "query": query}]}, Continuation(build)]


def recommend_then(
    query: str | None, build: Callable[[dict[str, Any]], dict[str, Any]]
) -> list[Proposal]:
    """Recommend for a real topic, then answer from the result."""
    read = {"kind": "recommend", **({"topic": query} if query else {})}
    return [{"reads": [read]}, Continuation(build)]


def lookup_then_reply(kind: str, query: str, text: str) -> list[Proposal]:
    """Look up for real, then answer from what came back."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        assert lookup_matches(request, kind), f"检索没有返回可回答的 {kind}：{request.get('query_results')}"
        return {"reply": text}

    return lookup_then(kind, query, build)


def recommend_then_reply(query: str | None, text: str) -> list[Proposal]:
    """Recommend for a real topic, then answer from the result."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        assert topic_rows(request), f"检索没有返回可推荐的菜：{request.get('query_results')}"
        return {"reply": text}

    return recommend_then(query, build)


def continued(build: Callable[[dict[str, Any]], dict[str, Any]]) -> Continuation:
    """Mark the next step as this turn's answer stage, waiting for real results."""
    return Continuation(build)


def _last_result(
    request: dict[str, Any], *, kind: str | None = None, lookup_kind: str | None = None
) -> dict[str, Any] | None:
    for result in reversed(request.get("query_results") or []):
        if result.get("status") != "completed":
            continue
        if lookup_kind is not None:
            if result.get("kind") == "lookup" and result.get("lookup_kind") == lookup_kind:
                return result
        elif result.get("kind") == kind:
            return result
    return None


def lookup_matches(request: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The rows a ``lookup`` of ``kind`` really returned this turn."""
    result = _last_result(request, lookup_kind=kind)
    assert result is not None, f"本轮没有 {kind} lookup 的真实结果: {request.get('query_results')}"
    return list(result.get("matches") or [])


def topic_rows(request: dict[str, Any], key: str = "buildable_dishes") -> list[dict[str, Any]]:
    """The rows a topic ``recommend`` really returned this turn."""
    result = _last_result(request, kind="recommend")
    assert result is not None, f"本轮没有 recommend 的真实结果: {request.get('query_results')}"
    return list(result.get(key) or [])


def plan_group_ref(request: dict[str, Any], group_id: str) -> str:
    plan = request.get("current_plan") or {}
    for row in plan.get("groups") or []:
        if str(row.get("group_id")) == group_id:
            return str(row["ref"])
    raise AssertionError(f"当前方案里没有分组 {group_id}: {plan.get('groups')}")


def plan_item_ref(request: dict[str, Any], sku_id: str) -> str:
    plan = request.get("current_plan") or {}
    for row in plan.get("items") or []:
        if str(row.get("sku_id")) == sku_id:
            return str(row["ref"])
    raise AssertionError(f"当前方案里没有商品 {sku_id}: {plan.get('items')}")


def first_group_ref(request: dict[str, Any]) -> str:
    groups = (request.get("current_plan") or {}).get("groups") or []
    assert groups, "当前方案没有分组"
    return str(groups[0]["ref"])


def first_item_ref(request: dict[str, Any]) -> str:
    items = (request.get("current_plan") or {}).get("items") or []
    assert items, "当前方案没有商品行"
    return str(items[0]["ref"])

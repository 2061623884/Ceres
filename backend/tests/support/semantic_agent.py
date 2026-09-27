"""Offline test double for the semantic proposal protocol.

The product still requires a live provider; this only removes the network from
the semantic loop so the protocol, the compiler and the persistence can be
exercised deterministically.
"""

from __future__ import annotations

from typing import Any, Callable

from app.llm.errors import LLMProviderError

from support.reactive_semantic import stated_people

Proposal = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | Exception


class Continuation:
    """The second model call of the same turn: it waits for real retrieval.

    A plain dict or callable is one model call. A ``Continuation`` is only handed
    over once the turn really carries ``query_results``, so a script written as
    "look up, then use what came back" can never be consumed by a *later* user
    turn — the mismatch fails loudly instead of silently answering with the
    wrong step.
    """

    def __init__(self, build: Callable[[dict[str, Any]], dict[str, Any]]):
        self.build = build


class ScriptedSemanticProvider:
    """Returns the scripted proposal for each propose step, in order.

    A proposal may be a dict, a callable taking the request (useful when the
    refs are only known at call time), an exception instance to raise, or a
    ``Continuation`` (see above).
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
            raise LLMProviderError(
                "EMPTY_MODEL_RESPONSE", "脚本用尽：没有更多提案", retryable=True
            )
        item = self.proposals[0]
        if isinstance(item, Continuation) and not request.get("query_results"):
            raise AssertionError(
                "脚本的下一步在等待检索回灌，但这一轮没有 query_results："
                "说明上一轮的检索脚本没有被消费（多步脚本与实际模型调用数不一致）"
            )
        self.proposals.pop(0)
        if isinstance(item, Continuation):
            return item.build(request)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            result = item(request)
        else:
            result = item
        if on_reply_delta is not None and isinstance(result, dict):
            reply = result.get("reply")
            if isinstance(reply, str) and reply:
                on_reply_delta(reply, False, False)
        return result


# --------------------------------------------------------------------- builders


def candidates_of(request: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The candidate rows of one kind from a propose request."""
    key = {"dish": "dishes", "product": "products", "scenario": "scenarios"}[kind]
    return list((request.get("candidates") or {}).get(key) or [])


def new_goal_for(kind: str, name: str, *, modifiers: dict[str, Any] | None = None) -> dict[str, Any]:
    """The goal statement that matches one ``add`` of ``kind``.

    A dish or a scenario is a self-cooked meal; a product is a purchase. The
    headcount is the one the script states, because the server may not invent it.
    """
    modifiers = modifiers or {}
    if kind == "product":
        goal: dict[str, Any] = {"kind": "product_purchase", "items": [name], "target_name": name}
    else:
        goal = {
            "kind": "meal_plan",
            "fulfillment_mode": "unspecified",
            "target_name": name,
        }
    constraints: dict[str, Any] = {}
    if modifiers.get("people"):
        constraints["people"] = modifiers["people"]
    if modifiers.get("constraints"):
        constraints.update(modifiers["constraints"])
    if constraints:
        goal["constraints"] = constraints
    return goal


def goal_of(
    kind: str,
    name: str,
    *,
    people: int | None = None,
    mode: str = "unspecified",
    items: list[str] | None = None,
) -> dict[str, Any]:
    """One goal as the *model* states it, with the headcount it really states."""
    if kind == "product":
        goal: dict[str, Any] = {"kind": "product_purchase", "target_name": name}
        if items is not None:
            goal["items"] = list(items)
        else:
            goal["items"] = [name]
        return goal
    goal = {"kind": "meal_plan", "fulfillment_mode": mode, "target_name": name}
    if people:
        goal["constraints"] = {"people": people}
    return goal


def request_new(
    kind: str,
    name: str,
    *,
    relation: str = "new",
    people: int | None = None,
    mode: str = "unspecified",
    items: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The understanding for "start/append/switch to this goal"."""
    understanding: dict[str, Any] = {
        "speech_act": "request_action",
        "goal_relation": relation,
        "new_goal": goal_of(kind, name, people=people, mode=mode, items=items),
    }
    understanding.update(extra)
    return understanding


def request_amend(
    *,
    focus: str | None = None,
    changes: dict[str, Any] | None = None,
    speech_act: str = "request_action",
) -> dict[str, Any]:
    """The understanding for "act on the thing I am pointing at"."""
    understanding: dict[str, Any] = {"speech_act": speech_act, "goal_relation": "amend"}
    if focus is not None:
        understanding["focus_ref"] = focus
    if changes is not None:
        understanding["changes"] = changes
    return understanding


def with_understanding(
    proposal: dict[str, Any],
    *,
    relation: str = "new",
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the understanding an add-only script implies (when it has none).

    A self-cooked meal is generated per person, so the scripted model must state
    the headcount it read from the shopper. When the script itself does not carry
    one, the headcount the *user message* states is used — never an invented
    default: a model that reports a number the shopper never said is exactly the
    fabrication the server refuses to make on its own.
    """
    if not proposal.get("mutations") or proposal.get("understanding"):
        return proposal
    mutation = proposal["mutations"][0]
    ref = str(mutation.get("candidate_ref") or "")
    kind = {"d": "dish", "s": "scenario", "p": "product"}.get(ref[:1], "dish")
    modifiers = dict(mutation)
    if (
        kind in ("dish", "scenario")
        and not modifiers.get("people")
        and request is not None
    ):
        stated = stated_people(str(request.get("user_message") or ""))
        if not stated:
            # A follow-up append does not repeat the headcount; the constraint the
            # shopper already established this session is what the model carries
            # forward. It is still a fact the user stated — never a default.
            requirements = request.get("requirements") or {}
            stated = requirements.get("people")
        if stated:
            modifiers["people"] = stated
    return {
        **proposal,
        "understanding": {
            "speech_act": "request_action",
            "goal_relation": relation,
            "new_goal": new_goal_for(kind, str(mutation.get("name") or ""), modifiers=modifiers),
        },
    }


def add_first(kind: str, **modifiers: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Add the first candidate of ``kind``; refs are resolved at call time."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, kind)
        assert rows, f"没有可用的 {kind} 候选"
        mutation: dict[str, Any] = {"verb": "add", "candidate_ref": rows[0]["ref"], "name": rows[0]["name"]}
        mutation.update(modifiers)
        return with_understanding({"mutations": [mutation]}, request=request)

    return build


def add_named(kind: str, name_fragment: str, **modifiers: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Add the candidate whose display name contains ``name_fragment``."""

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, kind)
        for row in rows:
            if name_fragment in str(row.get("name") or ""):
                mutation: dict[str, Any] = {"verb": "add", "candidate_ref": row["ref"], "name": row["name"]}
                mutation.update(modifiers)
                return with_understanding({"mutations": [mutation]}, request=request)
        raise AssertionError(f"候选清单里没有名称含「{name_fragment}」的 {kind}: {rows}")

    return build


def add_dish_preferring(
    name_fragment: str, **modifiers: Any
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Add a dish candidate, preferring one whose name contains the fragment.

    Falls back to the first dish candidate so the test exercises the protocol
    rather than the catalog's ordering.
    """

    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = candidates_of(request, "dish")
        assert rows, "没有可用的 dish 候选"
        chosen = next(
            (r for r in rows if name_fragment in str(r.get("name") or "")), rows[0]
        )
        mutation: dict[str, Any] = {"verb": "add", "candidate_ref": chosen["ref"], "name": chosen["name"]}
        mutation.update(modifiers)
        return with_understanding({"mutations": [mutation]}, request=request)

    return build


def reply_only(text: str) -> dict[str, Any]:
    return {"reply": text}


# ------------------------------------------------- retrieval-driven two-step scripts
#
# These helpers exist so a test never has to pretend a product was already
# retrieved. The first step asks for a real lookup; the second step is a
# ``Continuation`` that reads the ref the *server* issued and would fail loudly
# if no retrieval result came back. Nothing here falls back to "the first row".


def _last_result(request: dict[str, Any], *, kind: str | None = None,
                 lookup_kind: str | None = None) -> dict[str, Any] | None:
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
    assert result is not None, (
        f"本轮没有 {kind} lookup 的真实结果: {request.get('query_results')}"
    )
    return list(result.get("matches") or [])


def topic_rows(request: dict[str, Any], key: str = "buildable_dishes") -> list[dict[str, Any]]:
    """The rows a topic ``recommend`` really returned this turn."""
    result = _last_result(request, kind="recommend")
    assert result is not None, (
        f"本轮没有 recommend 的真实结果: {request.get('query_results')}"
    )
    return list(result.get(key) or [])


def continued(build: Callable[[dict[str, Any]], dict[str, Any]]) -> Continuation:
    """Mark the next step as "call 2 of this turn", waiting for real results."""
    return Continuation(build)


def lookup_then(
    kind: str,
    query: str,
    build: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    purchase: bool = False,
) -> list[Proposal]:
    """Two model calls: retrieve for real, then build the answer from it.

    ``build`` receives the second request, whose ``candidates`` already contain
    the rows the lookup really returned — so an ordinary callable such as
    ``add_first("product")`` works again, but only because a retrieval happened.
    """
    step: dict[str, Any] = {"lookups": [{"kind": kind, "query": query}]}
    if purchase:
        step["purchase_requested"] = True
        step["understanding"] = {"speech_act": "request_action"}
    return [step, Continuation(build)]


def _pick(rows: list[dict[str, Any]], name_fragment: str | None, label: str) -> dict[str, Any]:
    if name_fragment is None:
        assert rows, f"检索没有返回任何 {label}，不能用未检索到的对象"
        return rows[0]
    for row in rows:
        if name_fragment in str(row.get("name") or ""):
            return row
    # Never "closest match": a name that was asked for by name must match by name.
    raise AssertionError(f"检索结果里没有名称含「{name_fragment}」的 {label}：{rows}")


def lookup_then_add(
    kind: str,
    query: str,
    name_fragment: str | None = None,
    *,
    purchase: bool = True,
    **modifiers: Any,
) -> list[Proposal]:
    """Two model calls: retrieve for real, then add the row that came back.

    The first step states ``request_action`` because that — not the legacy flag —
    is what lets the turn write after the read.
    """
    step: dict[str, Any] = {"lookups": [{"kind": kind, "query": query}]}
    if purchase:
        step["purchase_requested"] = True
        step["understanding"] = {"speech_act": "request_action"}

    def build(request: dict[str, Any]) -> dict[str, Any]:
        row = _pick(lookup_matches(request, kind), name_fragment, kind)
        mutation = {"verb": "add", "candidate_ref": row["ref"], "name": row["name"]}
        mutation.update(modifiers)
        return with_understanding({"mutations": [mutation]}, request=request)

    return [step, Continuation(build)]


def lookup_then_add_id(
    kind: str,
    query: str,
    target_id: str,
    *,
    purchase: bool = True,
    **modifiers: Any,
) -> list[Proposal]:
    """Two model calls: retrieve for real, then add the row with this target id.

    The id is the business identity (``dish-fanqie-chao-dan``, a ``sku_id``), so a
    test can name a target without knowing the opaque ref the server will issue —
    the ref still comes from the real retrieval result, never from the test.
    """
    step: dict[str, Any] = {"lookups": [{"kind": kind, "query": query}]}
    if purchase:
        step["purchase_requested"] = True
        step["understanding"] = {"speech_act": "request_action"}

    def build(request: dict[str, Any]) -> dict[str, Any]:
        for row in lookup_matches(request, kind):
            if str(row.get("target_id") or "") == str(target_id):
                mutation = {"verb": "add", "candidate_ref": row["ref"], "name": row["name"]}
                mutation.update(modifiers)
                return with_understanding({"mutations": [mutation]}, request=request)
        raise AssertionError(
            f"检索结果里没有 target_id 为 {target_id} 的 {kind}: "
            f"{lookup_matches(request, kind)}"
        )

    return [step, Continuation(build)]


def recommend_then(
    query: str | None,
    build: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    purchase: bool = False,
) -> list[Proposal]:
    """Two model calls: recommend for a real topic, then use the result."""
    step: dict[str, Any] = {"queries": [{"kind": "recommend", **({"query": query} if query else {})}]}
    if purchase:
        step["purchase_requested"] = True
        step["understanding"] = {"speech_act": "request_action"}
    return [step, Continuation(build)]


def lookup_then_reply(kind: str, query: str, text: str) -> list[Proposal]:
    """Two model calls: retrieve for real, then answer from what came back."""
    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = lookup_matches(request, kind)
        assert rows, f"检索没有返回可回答的 {kind}：{request.get('query_results')}"
        return {"reply": text}

    return [{"lookups": [{"kind": kind, "query": query}]}, Continuation(build)]


def recommend_then_add(
    query: str | None,
    name_fragment: str | None = None,
    *,
    purchase: bool = True,
    **modifiers: Any,
) -> list[Proposal]:
    """Two model calls: recommend for a real topic, then add a returned dish."""
    step: dict[str, Any] = {"queries": [{"kind": "recommend", **({"query": query} if query else {})}]}
    if purchase:
        step["purchase_requested"] = True
        step["understanding"] = {"speech_act": "request_action"}

    def build(request: dict[str, Any]) -> dict[str, Any]:
        row = _pick(topic_rows(request), name_fragment, "dish")
        mutation = {"verb": "add", "candidate_ref": row["ref"], "name": row["name"]}
        mutation.update(modifiers)
        return with_understanding({"mutations": [mutation]}, request=request)

    return [step, Continuation(build)]


def recommend_then_reply(query: str | None, text: str) -> list[Proposal]:
    """Two model calls: recommend for a real topic, then answer from the result."""
    def build(request: dict[str, Any]) -> dict[str, Any]:
        rows = topic_rows(request)
        assert rows, f"检索没有返回可推荐的菜：{request.get('query_results')}"
        return {"reply": text}

    return [
        {"queries": [{"kind": "recommend", **({"query": query} if query else {})}]},
        Continuation(build),
    ]


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
    plan = request.get("current_plan") or {}
    groups = plan.get("groups") or []
    assert groups, "当前方案没有分组"
    return str(groups[0]["ref"])


def first_item_ref(request: dict[str, Any]) -> str:
    plan = request.get("current_plan") or {}
    items = plan.get("items") or []
    assert items, "当前方案没有商品行"
    return str(items[0]["ref"])


def empty_proposal() -> dict[str, Any]:
    return {}

"""P0 purchase-intent contract: coverage intents, gaps and requirement evidence.

This module is the single vocabulary shared by every plan path (dish / product /
scenario / merge / revise / refresh / row-add). It is pure: no ORM, no session,
no pricing. Keeping the rules here is what stops the five ``can_confirm``
producers from drifting apart.

Frozen here (see
``docs/plans/2026-09-19-purchase-intent-p0-implementation.md``):

* ``coverage_intent`` is what the caller *allows* (``full`` / ``partial_ok`` /
  ``user_supplied``); ``coverage_mode`` is what the plan *turned out to be*.
  ``full`` never authorizes an incomplete confirmation: a plan with a real gap
  may still be ``partial``, but it is not confirmable unless the caller allowed
  ``partial_ok`` (``user_supplied`` covers the user-supplied case). A plan that
  predates P0, or a request that omits the field, means ``full``.
* ``gaps`` is the one structured authority for supply/broken-requirement gaps.
  ``uncovered_items`` stays exactly what it always was — the required rows the
  user did not tick — and is produced as a projection, not a second gap list.

Two dimensional rules that are easy to get wrong and are therefore enforced here:

* a requirement's own amount lives in ``required_quantity``/``unit``
  (g / ml / pc), while ``requested_pack_count`` / ``available_quantity`` /
  ``shortfall_quantity`` are *packs*. The two are never mixed.
* a gap's identity is its requirement (``required_item_id`` when present, else a
  group+key pair), and a row that now carries that requirement is the authority:
  an older carried gap for the same requirement is dropped, not re-added.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

#: What a caller may allow.
COVERAGE_INTENTS = ("full", "partial_ok", "user_supplied")
#: The default for building a draft (default partial drafts, per the P0 grant).
GENERATION_INTENT = "partial_ok"
#: What an omitted/legacy value means: strict, no implicit incomplete confirmation.
LEGACY_INTENT = "full"

#: Gap kinds. ``unknown`` is never a disguised stock-out: ``unknown_of`` says
#: which attribute really is unverified.
GAP_KINDS = ("not_found", "out_of_stock", "insufficient_stock", "unknown")
UNKNOWN_FIELDS = ("availability", "quantity")
#: Availability of a plan line. Rows carrying ``out_of_stock`` / ``not_found`` /
#: ``unknown`` are never kept as selectable lines.
AVAILABILITY_STATES = (
    "available",
    "insufficient_stock",
    "out_of_stock",
    "not_found",
    "unknown",
)
SELECTABLE_AVAILABILITY = ("available", "insufficient_stock")

CORE = "core"
OPTIONAL = "optional"


def normalize_intent(value: Any) -> str:
    """A coverage intent we can act on; anything else is the strict legacy one."""
    text = str(value or "").strip()
    return text if text in COVERAGE_INTENTS else LEGACY_INTENT


def requiredness_for_role(role: Any) -> str:
    """``required`` rows are core; ``pantry``/``optional`` rows are not."""
    return CORE if str(role or "required") == "required" else OPTIONAL


def requirement_id(target_kind: str, target_id: str, key: str) -> str:
    """Stable requirement id, independent of client rendering order."""
    return f"{target_kind}:{target_id}#{key}"


def requirement_key(value: dict[str, Any]) -> str:
    """Canonical requirement identity of a gap, a row or a contribution.

    ``required_item_id`` is the authority because it is stable across rebuilds and
    across two targets that share one SKU; when it is absent (a legacy row or a
    row-less gap) the group plus its own key is used instead.
    """
    requirement = value.get("requirement") if isinstance(value.get("requirement"), dict) else {}
    required_item_id = value.get("required_item_id") or requirement.get("required_item_id")
    if required_item_id:
        return str(required_item_id)
    group_id = str(value.get("group_id") or "")
    tail = (
        requirement.get("ingredient_id")
        or value.get("ingredient_id")
        or requirement.get("component_id")
        or value.get("component_id")
        or value.get("key")
        or value.get("sku_id")
        or "-"
    )
    return f"{group_id}#{tail}"


def gap_id(group_id: str, kind: str, key: str | None) -> str:
    return f"{group_id}|{kind}|{key or '-'}"


def amount_from_needed(needed: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """The stated amount of a recipe requirement, in its own unit.

    Exactly one of ``quantity_g`` / ``quantity_ml`` / ``quantity_pc`` is stated by
    the fixtures; anything absent stays ``None`` instead of being invented.
    """
    data = needed or {}
    for key, unit in (("quantity_g", "g"), ("quantity_ml", "ml"), ("quantity_pc", "pc")):
        value = data.get(key)
        if value is not None:
            return float(value), unit
    return None, None


def make_requirement(
    *,
    target_kind: str,
    target_id: str,
    key: str,
    role: str,
    name: str | None = None,
    ingredient_id: str | None = None,
    component_id: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The minimal requirement evidence carried on a row (or a gap)."""
    return {
        "required_item_id": requirement_id(target_kind, target_id, key),
        "name": name,
        "ingredient_id": ingredient_id,
        "component_id": component_id,
        "quantity": quantity,
        "unit": unit,
        "quantity_known": quantity is not None,
        "requiredness": requiredness_for_role(role),
        "source": dict(source) if source else None,
    }


def gap_message(
    kind: str,
    *,
    name: str | None,
    unknown_of: str | None = None,
    available_quantity: int | None = None,
    requiredness: str = CORE,
    requested_pack_count: int | None = None,
) -> str:
    """Server-composed wording.

    It states only what was really checked: a catalogue miss is a catalogue miss
    (never "the store does not sell it"), an unknown pack size says how many
    packs were actually suggested — or that nothing was added when there is no
    honest pack count at all. Money and units are never invented here.
    """
    label = name or "该食材"
    if kind == "not_found":
        if requiredness == CORE:
            return f"当前目录里没有找到{label}，暂时无法配齐原目标。"
        return f"本次检索/当前目录里没有找到{label}，已给出其余可选商品。"
    if kind == "out_of_stock":
        return f"{label} 当前库存为 0，本次无法购买。"
    if kind == "insufficient_stock":
        if available_quantity:
            return (
                f"{label} 库存不足，本次只准备了可售的 {available_quantity} 件，"
                "不足的部分保留为缺口。"
            )
        return f"{label} 库存不足，只准备了可售的部分，不足的部分保留为缺口。"
    if kind == "unknown" and unknown_of == "quantity":
        if requested_pack_count:
            return (
                f"{label} 的用量或包装规格未核实，按最小包装给了 {requested_pack_count} 件建议，"
                "不能视为已配齐。"
            )
        return f"{label} 的用量或包装规格无法换算，本次没有把它加入购买，不能视为已配齐。"
    return f"{label} 的库存或供给信息未核实，本次没有把它加入购买。"


def make_gap(
    *,
    group_id: str,
    target_kind: str,
    target_id: str,
    kind: str,
    requiredness: str = CORE,
    key: str | None = None,
    required_item_id: str | None = None,
    required_item_ids: list[str] | None = None,
    ingredient_id: str | None = None,
    component_id: str | None = None,
    name: str | None = None,
    sku_id: str | None = None,
    required_quantity: float | None = None,
    unit: str | None = None,
    quantity_known: bool | None = None,
    available_quantity: int | None = None,
    requested_pack_count: int | None = None,
    shortfall_quantity: int | None = None,
    unknown_of: str | None = None,
    source: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """One structured gap.

    ``required_quantity``/``unit`` are the *requirement's* own amount;
    ``requested_pack_count``/``available_quantity``/``shortfall_quantity`` are
    packs. ``required_item_ids`` lists every requirement the row really covers
    when two targets share one SKU. ``message`` is display text, never a fact
    source.
    """
    gap_kind = kind if kind in GAP_KINDS else "unknown"
    unknown_field = unknown_of if unknown_of in UNKNOWN_FIELDS else None
    if gap_kind != "unknown":
        unknown_field = None
    identity = str(
        required_item_id
        or f"{group_id}#{key or ingredient_id or component_id or sku_id or '-'}"
    )
    all_required_item_ids = [str(value) for value in (required_item_ids or []) if value]
    if required_item_id and str(required_item_id) not in all_required_item_ids:
        all_required_item_ids.append(str(required_item_id))
    text = message
    if not text:
        text = gap_message(
            gap_kind,
            name=name,
            unknown_of=unknown_field,
            available_quantity=available_quantity,
            requiredness=requiredness,
            requested_pack_count=requested_pack_count,
        )
        if len(all_required_item_ids) > 1 and gap_kind != "unknown":
            text += "（本行由多个目标共用，缺口按整行算。）"
    return {
        "gap_id": gap_id(group_id, gap_kind, identity),
        "group_id": group_id,
        "target_kind": target_kind,
        "target_id": target_id,
        "kind": gap_kind,
        "unknown_of": unknown_field,
        "requiredness": requiredness if requiredness in (CORE, OPTIONAL) else CORE,
        "required_item_id": required_item_id,
        "required_item_ids": all_required_item_ids or None,
        "ingredient_id": ingredient_id,
        "component_id": component_id,
        "name": name,
        "sku_id": sku_id,
        "required_quantity": required_quantity,
        "unit": unit,
        "quantity_known": quantity_known,
        "requested_pack_count": requested_pack_count,
        "available_quantity": available_quantity,
        "shortfall_quantity": shortfall_quantity,
        "source": dict(source) if source else None,
        "evidence": dict(evidence) if evidence else None,
        "message": text,
    }


def remaining_quantity(item: dict[str, Any]) -> int:
    """Packs still owed to the next batch confirmation."""
    return max(0, int(item.get("quantity") or 1) - int(item.get("added_quantity") or 0))


def _contexts(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The requirement identities one *present* row really covers.

    A shared SKU collapsed from several targets carries every contribution's
    requirement evidence, so each target keeps its own identity instead of the
    row silently reporting only the first one. A legacy contribution without its
    own evidence falls back to the row's, so evidence is never dropped.
    """
    row_requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
    contexts: list[dict[str, Any]] = []
    for contribution in item.get("contributions") or []:
        if not isinstance(contribution, dict):
            continue
        requirement = (
            contribution.get("requirement")
            if isinstance(contribution.get("requirement"), dict)
            else {}
        )
        contexts.append(
            {
                "group_id": str(
                    contribution.get("group_id") or item.get("group_id") or ""
                ),
                "required_item_id": contribution.get("required_item_id")
                or requirement.get("required_item_id")
                or item.get("required_item_id"),
                "requirement": requirement or row_requirement,
            }
        )
    if contexts:
        return contexts
    return [
        {
            "group_id": str(item.get("group_id") or ""),
            "required_item_id": item.get("required_item_id"),
            "requirement": row_requirement,
        }
    ]


def _context_gaps(
    item: dict[str, Any],
    context: dict[str, Any],
    required_item_ids: list[str],
) -> list[dict[str, Any]]:
    requirement = context.get("requirement") or {}
    required_item_id = context.get("required_item_id") or requirement.get(
        "required_item_id"
    )
    common: dict[str, Any] = {
        "group_id": str(context.get("group_id") or item.get("group_id") or ""),
        "target_kind": str(item.get("target_kind") or ""),
        "target_id": str(item.get("target_id") or ""),
        "requiredness": requiredness_for_role(item.get("role")),
        "key": required_item_id or str(item.get("sku_id") or "-"),
        "required_item_id": required_item_id,
        "required_item_ids": required_item_ids,
        "ingredient_id": requirement.get("ingredient_id"),
        "component_id": requirement.get("component_id"),
        "name": requirement.get("name") or item.get("name"),
        "sku_id": str(item.get("sku_id") or "") or None,
        # The requirement's own amount/unit — never a pack count.
        "required_quantity": requirement.get("quantity"),
        "unit": requirement.get("unit"),
        "quantity_known": requirement.get("quantity_known"),
        "source": requirement.get("source"),
        "evidence": item.get("evidence") if isinstance(item.get("evidence"), dict) else None,
    }
    available = item.get("max_addable_quantity")
    availability = str(item.get("availability") or "available")
    shortfall = int(item.get("shortfall_quantity") or 0)
    packed = int(item.get("quantity") or 0)
    wanted = int(item.get("recommended_quantity") or 0) or packed
    gaps: list[dict[str, Any]] = []
    if availability != "available" or shortfall > 0:
        kind = availability if availability in GAP_KINDS else "insufficient_stock"
        gaps.append(
            make_gap(
                kind=kind,
                # An unverified availability stays ``unknown`` so the wording never
                # reads as a stock-out claim.
                unknown_of="availability" if kind == "unknown" else None,
                available_quantity=int(available) if available is not None else None,
                requested_pack_count=wanted or None,
                shortfall_quantity=shortfall or None,
                **common,
            )
        )
    if str(item.get("pack_source") or "") == "assumed_one":
        # A missing pack spec is an *unknown quantity*: the one-pack suggestion is
        # kept, but it is never proof that the requirement is covered.
        gaps.append(
            make_gap(
                kind="unknown",
                unknown_of="quantity",
                requested_pack_count=packed or None,
                **common,
            )
        )
    return gaps


def _row_gaps(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The gaps a *present* row already proves (empty when it is covered).

    Every requirement the row covers gets its own gap, so two targets that share
    one SKU keep two identities (and removing one target retires only its gap).
    """
    contexts = _contexts(item)
    required_item_ids = [
        str(value)
        for value in (
            context.get("required_item_id")
            or (context.get("requirement") or {}).get("required_item_id")
            for context in contexts
        )
        if value
    ]
    gaps: list[dict[str, Any]] = []
    for context in contexts:
        gaps.extend(_context_gaps(item, context, required_item_ids))
    deduped: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        deduped.setdefault(gap["gap_id"], gap)
    return list(deduped.values())


def normalize_carried_gap(
    entry: dict[str, Any] | None,
    *,
    target_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fill a caller-provided gap (builders, refresh, merge) into full shape."""
    if not isinstance(entry, dict) or not entry.get("kind"):
        return None
    context = dict(target_context or {})
    for key in ("group_id", "target_kind", "target_id"):
        if entry.get(key):
            context[key] = entry[key]
    return make_gap(
        group_id=str(context.get("group_id") or ""),
        target_kind=str(context.get("target_kind") or ""),
        target_id=str(context.get("target_id") or ""),
        kind=str(entry["kind"]),
        requiredness=str(entry.get("requiredness") or CORE),
        key=entry.get("key")
        or entry.get("ingredient_id")
        or entry.get("component_id")
        or entry.get("sku_id"),
        required_item_id=entry.get("required_item_id"),
        required_item_ids=entry.get("required_item_ids"),
        ingredient_id=entry.get("ingredient_id"),
        component_id=entry.get("component_id"),
        name=entry.get("name"),
        sku_id=entry.get("sku_id"),
        required_quantity=entry.get("required_quantity"),
        unit=entry.get("unit"),
        quantity_known=entry.get("quantity_known"),
        available_quantity=entry.get("available_quantity"),
        requested_pack_count=entry.get("requested_pack_count"),
        shortfall_quantity=entry.get("shortfall_quantity"),
        unknown_of=entry.get("unknown_of"),
        source=entry.get("source"),
        evidence=entry.get("evidence"),
        message=entry.get("message"),
    )


def collect_gaps(
    carried: Iterable[dict[str, Any]] | None,
    items: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Row-derived gaps first, then carried gaps for requirements with no row.

    A row (or one of its contributions) that now carries a requirement is the
    authority for it: a carried gap for the same requirement is dropped, so a
    resolved or restocked row can never leave a stale gap behind, and no two gaps
    can describe the same requirement.
    """
    result: dict[str, dict[str, Any]] = {}
    present: set[str] = set()
    for item in items or []:
        for gap in _row_gaps(item):
            result[gap["gap_id"]] = gap
        present.add(requirement_key(item))
        for contribution in item.get("contributions") or []:
            if isinstance(contribution, dict):
                present.add(requirement_key(contribution))
    for gap in carried or []:
        normalized = normalize_carried_gap(gap)
        if normalized is None:
            continue
        if requirement_key(normalized) in present:
            continue
        result.setdefault(normalized["gap_id"], normalized)
    return list(result.values())


def is_advisory_gap(gap: dict[str, Any]) -> bool:
    """A gap that informs but does not make the plan partial on its own.

    An optional (pantry / freely-shoppable) row whose pack size is unknown is
    honestly reported — the one-pack suggestion is not proof of coverage — but it
    does not by itself downgrade the whole plan's requirement coverage. Every
    other gap does: a missing/out-of-stock component, a stock shortfall, or any
    unknown on a core requirement.
    """
    return (
        str(gap.get("kind") or "") == "unknown"
        and str(gap.get("unknown_of") or "quantity") == "quantity"
        and str(gap.get("requiredness") or CORE) != CORE
    )


def coverage(
    items: Iterable[dict[str, Any]] | None,
    gaps: Iterable[dict[str, Any]] | None,
    intent: Any = LEGACY_INTENT,
    *,
    user_supplied_ingredients: Iterable[str] | None = None,
    ignore_unselected_required: bool = False,
) -> dict[str, Any]:
    """The one coverage rule every plan path must agree on.

    ``full`` is strict: it never authorizes confirming an incomplete plan. A real
    gap still produces an honest ``partial`` result, it just is not confirmable
    until the caller asks for ``partial_ok`` (or the plan itself was built that
    way). ``ignore_unselected_required`` is for an ``alternatives`` plan, where a
    row that was not chosen is a legitimate comparison result.
    """
    rows = list(items or [])
    gap_list = [gap for gap in (gaps or []) if isinstance(gap, dict)]
    effective_intent = normalize_intent(intent)
    user_supplied = {str(value) for value in (user_supplied_ingredients or [])}

    selectable = [
        row for row in rows if str(row.get("availability") or "available") in SELECTABLE_AVAILABILITY
    ]
    selected = [row for row in selectable if row.get("selected", True)]
    unselected_required = [
        row
        for row in rows
        if not ignore_unselected_required
        and str(row.get("role") or "required") == "required"
        and not row.get("selected", True)
        and str(row.get("availability") or "available") in SELECTABLE_AVAILABILITY
        and not (user_supplied & {str(value) for value in row.get("ingredient_ids") or []})
    ]
    uncovered_items = [
        {
            "sku_id": row.get("sku_id"),
            "ingredient_ids": list(row.get("ingredient_ids") or []),
            "required_item_id": row.get("required_item_id"),
        }
        for row in unselected_required
    ]
    over_stock = [
        str(row.get("sku_id"))
        for row in selected
        if int(row.get("max_addable_quantity") or 0) < remaining_quantity(row)
    ]
    degrading = [gap for gap in gap_list if not is_advisory_gap(gap)]

    if unselected_required and effective_intent not in ("partial_ok", "user_supplied"):
        coverage_mode = "uncovered"
    elif degrading or unselected_required:
        coverage_mode = "partial" if selected else "uncovered"
    elif effective_intent == "user_supplied":
        coverage_mode = "user_supplied"
    else:
        coverage_mode = "full"

    # Nothing left to confirm (every selected row is already in the cart) is not
    # a confirmable plan, whatever the coverage mode says.
    has_outstanding = any(remaining_quantity(row) > 0 for row in selected)
    can_confirm = (
        has_outstanding
        and not over_stock
        and coverage_mode in ("full", "partial", "user_supplied")
    )
    if coverage_mode == "uncovered":
        can_confirm = False
    if effective_intent == "full" and (degrading or unselected_required):
        # No implicit incomplete confirmation: the caller never allowed it.
        can_confirm = False
    return {
        "coverage_mode": coverage_mode,
        "can_confirm": can_confirm,
        "uncovered_items": uncovered_items,
        "over_stock": over_stock,
        "coverage_intent": effective_intent,
        "has_outstanding": has_outstanding,
    }


def gaps_signature(gaps: Iterable[dict[str, Any]] | None) -> str:
    """A stable digest so a coverage change advances the plan version."""
    normalized = sorted(
        [
            [
                str(gap.get("gap_id") or ""),
                str(gap.get("kind") or ""),
                str(gap.get("unknown_of") or ""),
                str(gap.get("requiredness") or ""),
                gap.get("available_quantity"),
                gap.get("requested_pack_count"),
                gap.get("shortfall_quantity"),
            ]
            for gap in gaps or []
            if isinstance(gap, dict)
        ],
        key=lambda row: row[0],
    )
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def gap_notes(gaps: Iterable[dict[str, Any]] | None) -> list[str]:
    """Distinct, user-visible gap sentences, in plan order."""
    notes: list[str] = []
    for gap in gaps or []:
        if not isinstance(gap, dict):
            continue
        text = str(gap.get("message") or "").strip()
        if text and text not in notes:
            notes.append(text)
    return notes


__all__ = [
    "AVAILABILITY_STATES",
    "CORE",
    "COVERAGE_INTENTS",
    "GAP_KINDS",
    "GENERATION_INTENT",
    "LEGACY_INTENT",
    "OPTIONAL",
    "SELECTABLE_AVAILABILITY",
    "amount_from_needed",
    "collect_gaps",
    "coverage",
    "gap_id",
    "gap_message",
    "gap_notes",
    "gaps_signature",
    "is_advisory_gap",
    "make_gap",
    "make_requirement",
    "normalize_carried_gap",
    "normalize_intent",
    "remaining_quantity",
    "requiredness_for_role",
    "requirement_id",
    "requirement_key",
]

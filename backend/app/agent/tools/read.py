"""Read-only retrieval port for the guide loop.

This is the loop's only window onto real data. It answers "what does the store
actually have" and nothing else: it never writes a plan, never touches the cart,
and never authors the user-visible answer — the model does that, from the
structured facts returned here.

Every request ends with an explicit outcome, including "nothing matched", so the
model is told the work is finished instead of asking for it again — and including
"the turn ran out of time", which is reported as its own outcome instead of being
silently dropped. Read results only ever *widen* the turn's candidate set, which
is how the model can reference what it just found.

A query is really used. ``recommend`` with a topic retrieves for *that* topic
through the store's own dish aliases and sellable-product match; only a
topic-less ``recommend`` is an open exploration, and it says so. An empty result
stays empty — the first rows of the catalogue are never offered as an answer.

Every read kind — lookup, recommend, recipe — applies the same hard exclusions,
on the indexed route and on the pre-index path alike, and every one of them
reports the same retrieval evidence: which route ran, what was filtered, and
whether a named target collided with an exclusion or is gone. A read that could
not run is reported as failed; a read that ran and found nothing is empty, and
neither is ever reported as the other.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from app.agent.protocol import (
    CandidateSet,
    SemanticProposal,
    add_lookup_candidates,
)
from app.services.retrieval_index import IndexUnavailable, read_pointer
from app.services.retrieval_service import RetrievalService
from app.services.shopping_plan_service import ShoppingPlanService
from app.services.template_matcher import dish_display_name, load_templates
from app.services.template_plan_service import TemplatePlanService, expand_ingredient_terms
from app.services.validation_context import ValidationContext

#: Read outcomes. ``completed`` with no matches is still a finished read, and must
#: never be reported to the model as a failure or retried.
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

#: How many retrieved rows may be offered to the model per request.
MAX_LOOKUP_ROWS = 5

#: Why a read was never served: the turn's own budget ran out. It is a real,
#: reported outcome — never a silent drop and never a fake empty result.
REASON_DEADLINE = "turn_deadline_exceeded"


def searchable(text: str | None) -> bool:
    """Whether a query is a real retrieval input.

    A blank or punctuation-only string is not: ``?`` must never match a product
    whose name happens to contain it, and an empty query must never be widened
    into "show me everything". This is input validation, not semantic inference.
    """
    return any(char.isalnum() for char in (text or ""))


class ReadTools:
    """The real read-only port, backed by the existing catalog/plan services."""

    def __init__(
        self,
        db: Session,
        *,
        store_id: str,
        delivery_zone_id: str,
        active_template_id: str | None = None,
        purchase_summary: dict[str, Any] | None = None,
        deadline_expired: Callable[[], bool] | None = None,
        requirements: Any | None = None,
        retrieval: RetrievalService | None = None,
    ):
        self.db = db
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        #: The turn's real user constraints. Hard filters come from here, not from
        #: a dictionary a test handed in: "不要花生" only excludes peanut if the
        #: resolved requirements say so.
        self.requirements = requirements
        self._retrieval_service = retrieval
        #: The dish the shopper is already working on, used by a recipe query that
        #: does not name one.
        self.active_template_id = active_template_id
        #: The real confirmed-cart summary resolved for this turn.
        self.purchase_summary = purchase_summary
        #: The turn's own budget, checked *between* reads. A round with several
        #: reads is served in order, and a read that starts after the budget is
        #: spent is not a read at all — but one already in flight is never
        #: interrupted, because nothing here can interrupt a blocking call.
        self._deadline_expired = deadline_expired

    # -------------------------------------------------------------- loop port

    def serve(
        self,
        proposal: SemanticProposal,
        candidates: CandidateSet,
        *,
        lookup_limit: int,
    ) -> list[dict[str, Any]]:
        """Serve every read-only request of one proposal, in order.

        Every request still ends with exactly one explicit outcome, including the
        ones the turn's budget no longer allowed to run.
        """
        results: list[dict[str, Any]] = []
        for index, lookup in enumerate(proposal.lookups):
            if self._expired():
                results.append(
                    self._deadline_skipped(
                        kind="lookup", lookup_kind=lookup.kind, query=lookup.query
                    )
                )
                continue
            if index >= lookup_limit:
                results.append(
                    {
                        "kind": "lookup",
                        "lookup_kind": lookup.kind,
                        "query": lookup.query,
                        "status": STATUS_SKIPPED,
                        "reason": "lookup_budget_exhausted",
                        "matches": [],
                    }
                )
                continue
            results.append(self._lookup(lookup, candidates))
        for query in proposal.queries:
            if self._expired():
                results.append(self._deadline_skipped(kind=query.kind, query=query.query))
                continue
            results.append(self._query(query, candidates))
        return results

    def _expired(self) -> bool:
        return bool(self._deadline_expired is not None and self._deadline_expired())

    @staticmethod
    def _deadline_skipped(
        *, kind: str, lookup_kind: str | None = None, query: Any = None
    ) -> dict[str, Any]:
        """One request the turn ran out of time to serve. Reported, not dropped."""
        result: dict[str, Any] = {
            "kind": kind,
            "status": STATUS_SKIPPED,
            "reason": REASON_DEADLINE,
            "message": "本轮处理超时，这个检索没有执行。",
            "query": query,
        }
        if lookup_kind is not None:
            result["lookup_kind"] = lookup_kind
            result["matches"] = []
        return result

    # ------------------------------------------------------------------ lookups

    # ------------------------------------------------------- retrieval service

    def _validation_context(
        self,
        *,
        extra_excluded: list[str] | None = None,
        extra_budget_fen: int | None = None,
    ) -> ValidationContext | None:
        """The turn's real constraints, merged with what this read stated.

        An exclusion the shopper says *now* is a hard filter even on a first
        turn, before any task state exists — otherwise "不要花生" would be left
        to the embedding route to "understand".

        The merge is a **union** on exclusions: a read can add one, and can never
        silently drop one that is already saved. Budget keeps the stricter of the
        two for the same reason.
        """
        base = None
        if self.requirements is not None:
            base = ValidationContext.from_requirements(
                self.requirements,
                store_id=self.store_id,
                delivery_zone_id=self.delivery_zone_id,
                active_template_id=self.active_template_id,
            )
        extra_excluded = [x for x in (extra_excluded or []) if str(x).strip()]
        if base is None and not extra_excluded and extra_budget_fen is None:
            return None
        if base is None:
            from app.agent.state import Requirements

            base = ValidationContext(
                store_id=self.store_id,
                delivery_zone_id=self.delivery_zone_id,
                requirements=Requirements(),
                active_template_id=self.active_template_id,
            )
        merged_excluded = list(
            dict.fromkeys([*base.excluded_ingredients, *extra_excluded])
        )
        budgets = [b for b in (base.budget_fen, extra_budget_fen) if b is not None]
        return replace(
            base,
            excluded_ingredients=merged_excluded,
            budget_fen=min(budgets) if budgets else None,
        )

    def _applied_constraints(
        self,
        extra_excluded: list[str] | None,
        extra_budget_fen: int | None,
    ) -> tuple[list[str], int | None]:
        """The exclusions and budget this read must honour, after the union.

        Both the indexed route and the pre-index path read the filter from here,
        so a constraint cannot apply on one route and be silently ignored on the
        other.
        """
        context = self._validation_context(
            extra_excluded=extra_excluded, extra_budget_fen=extra_budget_fen
        )
        if context is None:
            return [], None
        return [str(x) for x in context.excluded_ingredients or [] if str(x).strip()], (
            context.budget_fen
        )

    @staticmethod
    def _retrieval_evidence(retrieval: dict[str, Any]) -> dict[str, Any]:
        """The retrieval fields every read result carries, built in one place.

        Which route ran, what was filtered, why a route degraded, and a named
        target that collided with an exclusion or is gone from the store all have
        to reach the model: without them a degraded read is indistinguishable
        from a clean one, and "we could not look" from "there is nothing".
        """
        evidence: dict[str, Any] = {
            "retrieval_status": retrieval.get("status"),
            "retrieval_mode": retrieval.get("retrieval_mode"),
            "fallback_reason": retrieval.get("fallback_reason"),
            "index_version": retrieval.get("index_version"),
            "filters_applied": retrieval.get("filters_applied"),
        }
        for key in ("code", "message", "conflict", "dropped_exact_match",
                    "unknown_constraints", "stale_document_ids", "index_update_required"):
            if retrieval.get(key):
                evidence[key] = retrieval[key]
        return evidence

    def _retrieval(
        self,
        kind: str,
        query: str,
        *,
        limit: int = MAX_LOOKUP_ROWS,
        extra_excluded: list[str] | None = None,
        extra_budget_fen: int | None = None,
    ) -> dict[str, Any] | None:
        """Run the shared retrieval service, or ``None`` if there is no index.

        A missing index is a real, reported state — the caller falls back to the
        pre-existing lookup path and says so in ``retrieval_status`` rather than
        pretending a semantic search happened.
        """
        service = self._retrieval_service
        if service is None:
            try:
                service = RetrievalService(
                    self.db, store_id=self.store_id, delivery_zone_id=self.delivery_zone_id
                )
            except Exception:  # pragma: no cover - configuration read only
                return None
        # No published index at all means this deployment has never had one: the
        # pre-index lookup path answers, labelled as such. An index that *exists*
        # but is incompatible is different — that is a real failure and is
        # reported instead of being papered over with the old path.
        if not service.index_configured:
            # Retrieval is not deployed here at all (no RETRIEVAL_INDEX_DIR). The
            # pre-index path answers, and every result says so.
            return None
        if read_pointer(service.index_root) is None:
            # Retrieval *is* deployed and the index is missing: that is a real
            # failure. Answering from the old path here would disguise a broken
            # deployment as a working lookup.
            return service.unavailable_result("INDEX_MISSING", "检索索引缺失，本轮没有执行检索。")
        if not service.describes_runtime_db():
            # The index exists but describes a different corpus. Same reasoning:
            # another snapshot's dishes must not be served under this store's name.
            return service.unavailable_result(
                "INDEX_STALE", "检索索引与当前运行库不一致，本轮没有执行检索。"
            )
        context = self._validation_context(
            extra_excluded=extra_excluded, extra_budget_fen=extra_budget_fen
        )
        try:
            if kind == "dish":
                return service.search_dishes(query, context=context, limit=limit)
            return service.search_products(query, context=context, limit=limit)
        except IndexUnavailable:
            return None

    def _lookup(self, lookup: Any, candidates: CandidateSet) -> dict[str, Any]:
        if not searchable(lookup.query):
            # Not a retrieval input: nothing is searched, and nothing is matched
            # by accident. `?` must never find a product whose name contains it.
            return {
                "kind": "lookup",
                "lookup_kind": lookup.kind,
                "query": lookup.query,
                "status": STATUS_FAILED,
                "code": "EMPTY_QUERY",
                "message": "检索词为空或只有符号，没有执行检索。请给出要查的菜名或商品名。",
                "matches": [],
            }
        retrieval = self._retrieval(
            lookup.kind,
            lookup.query,
            extra_excluded=list(getattr(lookup, "excluded_ingredients", []) or []),
            extra_budget_fen=getattr(lookup, "budget_fen", None),
        )
        if retrieval is None:
            return self._legacy_lookup(lookup, candidates)
        if retrieval["status"] == "unavailable":
            # Reported as a failure, not as "nothing matched": the store cannot
            # currently answer this kind of question at all.
            return {
                "kind": "lookup",
                "lookup_kind": lookup.kind,
                "query": lookup.query,
                "status": STATUS_FAILED,
                "code": retrieval.get("code") or "INDEX_UNAVAILABLE",
                "message": retrieval.get("message") or "检索索引不可用，本轮没有执行检索。",
                "retrieval_status": retrieval["status"],
                "index_version": retrieval.get("index_version"),
                "matches": [],
            }
        rows = [_lookup_row(lookup.kind, hit) for hit in retrieval["hits"]]
        refs = add_lookup_candidates(
            candidates, kind=lookup.kind, rows=rows, limit=MAX_LOOKUP_ROWS
        )
        by_id = {str(row.get("dish_id") or row.get("sku_id")): hit
                 for row, hit in zip(rows, retrieval["hits"])}
        matches: list[dict[str, Any]] = []
        for candidate in refs:
            hit = by_id.get(candidate.target_id) or {}
            matches.append(
                {
                    "ref": candidate.ref,
                    "name": candidate.name,
                    "target_id": candidate.target_id,
                    "match_kind": hit.get("match_kind"),
                    "evidence": hit.get("evidence"),
                    "review_status": hit.get("review_status"),
                    "stock_verified": hit.get("stock_verified"),
                    "unknown_constraints": hit.get("unknown_constraints"),
                }
            )
        return {
            "kind": "lookup",
            "lookup_kind": lookup.kind,
            "query": lookup.query,
            "status": STATUS_COMPLETED,
            "empty": not refs,
            **self._retrieval_evidence(retrieval),
            "matches": matches,
        }

    def _legacy_lookup(self, lookup: Any, candidates: CandidateSet) -> dict[str, Any]:
        """The pre-index lookup path, kept as an explicit reported fallback.

        Used only when no retrieval index is published. It is labelled
        ``unavailable`` so nothing downstream has to guess which route answered —
        and it applies the same hard exclusions the indexed route does, so a
        "不要花生" is not honoured only when an index happens to be deployed.
        """
        # The budget is merged into the same union, but this path builds no plan,
        # so only the exclusions can be applied here.
        excluded, _budget_fen = self._applied_constraints(
            list(getattr(lookup, "excluded_ingredients", []) or []),
            getattr(lookup, "budget_fen", None),
        )
        outcome: dict[str, Any] = {}
        if lookup.kind == "dish":
            search = self._legacy_dish_search(lookup.query, excluded=excluded)
            rows = _legacy_rows(search)
            outcome = self._legacy_outcome(search)
            refs = add_lookup_candidates(
                candidates, kind="dish", rows=rows, limit=MAX_LOOKUP_ROWS
            )
        else:
            rows = self.find_products(lookup.query, excluded=excluded)
            refs = add_lookup_candidates(
                candidates, kind="product", rows=rows, limit=MAX_LOOKUP_ROWS
            )
        result: dict[str, Any] = {
            "kind": "lookup",
            "lookup_kind": lookup.kind,
            "query": lookup.query,
            "status": STATUS_COMPLETED,
            "empty": not refs,
            "retrieval_status": "unavailable",
            "fallback_reason": "no_published_index",
            "filters_applied": _applied_exclusions(excluded),
            "matches": [
                {"ref": c.ref, "name": c.name, "target_id": c.target_id} for c in refs
            ],
        }
        result.update(outcome)
        if result["status"] == STATUS_FAILED:
            # A read that could not run is not an empty result.
            result.pop("empty", None)
        return result

    @staticmethod
    def _legacy_outcome(search: dict[str, Any]) -> dict[str, Any]:
        """Map a pre-index dish search onto the vocabulary every read uses.

        Three outcomes are kept apart: a hard conflict with a stated exclusion is
        stated as a conflict, a search that ran and matched nothing is empty, and
        a search that could not run is a failure. Collapsing the last two is
        exactly what would let "we could not look" read as "there is nothing".
        """
        if search.get("status") == "ok":
            return {}
        code = search.get("code")
        if code == "CONSTRAINT_CONFLICT":
            return {"conflict": {"code": code, "message": search.get("message")}}
        if code == "NO_MATCH":
            return {}
        return {
            "status": STATUS_FAILED,
            "code": code or "LEGACY_SEARCH_FAILED",
            "message": search.get("message") or "本店检索没有执行成功。",
        }

    def _legacy_dish_search(
        self, query: str, *, excluded: list[str] | None = None
    ) -> dict[str, Any]:
        """The pre-index dish search, exclusions included, raw result kept.

        The raw result is returned rather than only its rows because the code —
        a hard conflict, no match, a failed search — is evidence the caller has
        to report.
        """
        from app.agent.tools.search_dishes import search_dishes

        return search_dishes(self.db, query=query, exclude_ingredients=list(excluded or []))

    def search_dishes(
        self, query: str, *, excluded: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return _legacy_rows(self._legacy_dish_search(query, excluded=excluded))

    def find_products(
        self, query: str, *, excluded: list[str] | None = None
    ) -> list[dict[str, Any]]:
        rows = ShoppingPlanService(self.db, self.store_id).find_product_candidates(
            query, max_results=MAX_LOOKUP_ROWS
        )
        return _drop_excluded_products(rows, excluded)

    # ------------------------------------------------------------------- queries

    def _query(self, query: Any, candidates: CandidateSet) -> dict[str, Any]:
        facts = self._collect_query(
            query.kind,
            query.query,
            extra_excluded=list(getattr(query, "excluded_ingredients", []) or []),
            extra_budget_fen=getattr(query, "budget_fen", None),
        )
        facts["query"] = query.query
        for row in facts.get("buildable_dishes", []):
            row["ref"] = candidates.allocate("dish", str(row["dish_id"]), row["name"]).ref
        for row in facts.get("sellable_products", []):
            row["ref"] = candidates.allocate("product", str(row["sku_id"]), row["name"]).ref
        # A recipe query's candidates are candidates too: without a ref the model
        # can describe them but can never reference one, which is the only way it
        # is allowed to act on what it found.
        for row in facts.get("candidates", []):
            if row.get("dish_id"):
                row["ref"] = candidates.allocate("dish", str(row["dish_id"]), row["name"]).ref
        return facts

    def _collect_query(
        self,
        kind: str,
        query: str | None = None,
        *,
        extra_excluded: list[str] | None = None,
        extra_budget_fen: int | None = None,
    ) -> dict[str, Any]:
        """Fetch real facts for a read-only query.

        This is deliberately *not* a user-facing answer: the model writes the
        reply. The server's only job is to hand over verified facts.

        The constraints on a query are the same hard filters a lookup carries:
        they are unioned with the saved requirements, so a first-turn "不要花生"
        really excludes peanut from a recommendation or a recipe instead of being
        left to the retrieval route to "understand".
        """
        if kind == "recommend":
            excluded, budget_fen = self._applied_constraints(extra_excluded, extra_budget_fen)
            if query is not None:
                return self._recommend_topic(query, excluded=excluded, budget_fen=budget_fen)
            # No topic: an open exploration, explicitly labelled as one. Only
            # dishes this store can actually build are offered — no unrelated
            # products are mixed in to pad the list, and nothing here claims the
            # result satisfies a constraint (spiciness, cooking style) that the
            # data does not carry.
            planner = TemplatePlanService(self.db, self.store_id, self.delivery_zone_id)
            # ``scan=None`` walks every recipe instead of stopping after the first
            # 20 fixture rows. The deadline is honoured cooperatively: running out
            # of time is reported as an incomplete exploration, never as "there is
            # nothing this store can make".
            dishes = planner.suggest_buildable_dishes(
                limit=3,
                scan=None,
                deadline_expired=self._deadline_expired,
                excluded_ingredients=excluded,
            )
            incomplete = bool(getattr(planner, "last_suggest_scan_exhausted", False))
            return {
                "kind": "recommend",
                "status": STATUS_COMPLETED,
                "exploration": True,
                "incomplete": incomplete,
                "retrieval_status": "ok" if not incomplete else "degraded",
                "fallback_reason": "turn_deadline_exceeded" if incomplete else None,
                "filters_applied": _applied_exclusions(excluded),
                # A generated plan is not a verified purchase: the scan resolves
                # ingredients to sellable SKUs, but nothing here has checked stock,
                # pack size or the turn's budget.
                "stock_verified": False,
                "note": (
                    "开放式探索候选，只表示这些菜谱能生成采购方案；"
                    "库存、规格与预算都没有严格校验，不构成有货或价格承诺，也不代表已满足口味。"
                    if not incomplete
                    else "本轮时间不足，只考察了部分菜谱，结果不完整；不代表没有别的可做菜。"
                ),
                "buildable_dishes": [
                    {"dish_id": d.get("dish_id"), "name": d.get("name")}
                    for d in dishes
                    if d.get("name")
                ],
            }

        if kind == "recipe":
            if query:
                excluded, budget_fen = self._applied_constraints(
                    extra_excluded, extra_budget_fen
                )
                retrieval = self._retrieval(
                    "dish", query, extra_excluded=excluded, extra_budget_fen=budget_fen
                )
                if retrieval is None:
                    search = self._legacy_dish_search(query, excluded=excluded)
                    return self._legacy_recipe(query, search, excluded=excluded)
                if retrieval["status"] == "unavailable":
                    # The index is deployed and cannot answer. That is a failed
                    # read, not an empty recipe and not a pre-index lookup.
                    facts: dict[str, Any] = {
                        "kind": "recipe",
                        "status": STATUS_FAILED,
                        "query": query,
                        **self._retrieval_evidence(retrieval),
                        "candidates": [],
                        "steps_available": False,
                    }
                    facts.setdefault("code", "INDEX_UNAVAILABLE")
                    facts.setdefault("message", "检索索引不可用，本轮没有执行检索。")
                    return facts
                return {
                    "kind": "recipe",
                    "status": STATUS_COMPLETED,
                    "query": query,
                    "candidates": [_lookup_row("dish", hit) for hit in retrieval["hits"]],
                    # The whole retrieval evidence is carried alongside, so a
                    # degraded, conflicting or superseded answer is never reported
                    # as a clean completed search.
                    **self._retrieval_evidence(retrieval),
                    "empty": retrieval.get("empty"),
                    "steps_available": False,
                }
            dish_id = self.active_template_id
            dish = self._dish_by_id(dish_id) if dish_id else None
            return {
                "kind": "recipe",
                "status": STATUS_COMPLETED,
                "dish_id": dish_id,
                "name": dish_display_name(dish) if dish else None,
                "main_ingredients": [
                    item.get("ingredient_id") or item.get("name")
                    for item in (dish or {}).get("required_items") or []
                    if item.get("ingredient_id") or item.get("name")
                ],
                # No store-verified cooking steps; the model may offer clearly
                # labelled general cooking advice without inventing store facts.
                "steps_available": False,
            }

        if kind == "cart":
            summary = self.purchase_summary or {}
            return {
                "kind": "cart",
                "status": STATUS_COMPLETED,
                "confirmed": bool(summary.get("confirmed")),
                "items": [
                    {
                        "sku_id": i.get("sku_id"),
                        "name": i.get("name"),
                        "quantity": i.get("quantity"),
                        "line_total_fen": i.get("line_total_fen"),
                    }
                    for i in summary.get("items") or []
                ],
                "total_fen": summary.get("total_fen"),
            }

        if kind == "catalog":
            names = sorted(
                {
                    str(t.get("scenario") or t.get("name") or "").strip()
                    for t in load_templates(self.db)
                    if t.get("scenario") or t.get("name")
                }
            )[:20]
            return {"kind": "catalog", "status": STATUS_COMPLETED, "dish_names": names}

        return {
            "kind": kind,
            "status": STATUS_FAILED,
            "code": "UNKNOWN_QUERY_KIND",
            "message": f"不支持的查询类型: {kind}",
        }

    def _legacy_recipe(
        self, query: str, search: dict[str, Any], *, excluded: list[str]
    ) -> dict[str, Any]:
        """The pre-index recipe lookup, with its own evidence reported.

        A conflict with a hard exclusion is stated here too: without an index
        there is still no substitution of a similar dish for the one named.
        """
        rows = _legacy_rows(search)
        facts: dict[str, Any] = {
            "kind": "recipe",
            "status": STATUS_COMPLETED,
            "query": query,
            "candidates": rows[:MAX_LOOKUP_ROWS],
            "steps_available": False,
            "retrieval_status": "unavailable",
            "fallback_reason": "no_published_index",
            "filters_applied": _applied_exclusions(excluded),
            "empty": not rows,
        }
        if search.get("match_kind"):
            facts["match_kind"] = search["match_kind"]
        facts.update(self._legacy_outcome(search))
        if facts["status"] == STATUS_FAILED:
            facts.pop("empty", None)
        return facts

    def _recommend_topic(
        self, query: str, *, excluded: list[str], budget_fen: int | None
    ) -> dict[str, Any]:
        """A recommendation for the topic the shopper actually named.

        Both halves go through the existing local retrieval — dish aliases and
        usage labels for recipes, the store's own sellable-product match for
        goods. An empty result is reported as empty: falling back to "whatever is
        first in the catalogue" is exactly the defect this replaces.
        """
        if not searchable(query):
            return {
                "kind": "recommend",
                "status": STATUS_FAILED,
                "code": "EMPTY_QUERY",
                "message": "检索词为空或只有符号，没有执行检索。",
                "buildable_dishes": [],
                "sellable_products": [],
            }
        dish_retrieval = self._retrieval(
            "dish", query, extra_excluded=excluded, extra_budget_fen=budget_fen
        )
        product_retrieval = self._retrieval(
            "product", query, extra_excluded=excluded, extra_budget_fen=budget_fen
        )
        if dish_retrieval is not None or product_retrieval is not None:
            return self._recommend_from_retrieval(query, dish_retrieval, product_retrieval)
        dish_search = self._legacy_dish_search(query, excluded=excluded)
        dishes = _legacy_rows(dish_search)[:MAX_LOOKUP_ROWS]
        products = self.find_products(query, excluded=excluded)
        unavailable = {
            "status": "unavailable",
            "reason": "no_published_index",
            "hits": 0,
        }
        return {
            "kind": "recommend",
            "status": STATUS_COMPLETED,
            "query": query,
            "empty": not dishes and not products,
            "retrieval_status": "unavailable",
            "fallback_reason": "no_published_index",
            "filters_applied": _applied_exclusions(excluded),
            "partial_sources": {
                "dishes": {**unavailable, "hits": len(dishes)},
                "products": {**unavailable, "hits": len(products)},
            },
            # These are name/usage-tag matches — a dish whose name or usage tag
            # matched what was asked. Nobody has checked that its ingredients can
            # be covered at this store, and nothing here is a stock or price
            # promise. Availability is decided when a plan is actually built.
            "stock_verified": False,
            "note": (
                "按菜名/用途标签匹配到的菜谱，尚未校验是否配得齐，也不是库存或价格承诺；"
                "只有生成清单时才会校验真实商品与库存。"
            ),
            "buildable_dishes": [
                {
                    "dish_id": d.get("dish_id") or d.get("template_id"),
                    "name": d.get("name") or d.get("scenario") or "",
                }
                for d in dishes
                if d.get("dish_id") or d.get("template_id")
            ],
            "sellable_products": [
                {
                    "sku_id": p.get("sku_id"),
                    "name": p.get("name_zh") or p.get("name"),
                }
                for p in products
                if p.get("sku_id")
            ],
        }

    def _recommend_from_retrieval(
        self,
        query: str,
        dish_retrieval: dict[str, Any] | None,
        product_retrieval: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Combine the two independent sources and report partial failure honestly.

        One source succeeding and the other failing is *not* a successful
        recommendation, and it is certainly not "the store has no such product".
        The overall status is the worst of the two, and ``partial_sources``
        carries each side's own status and reason.
        """
        sources = {"dishes": dish_retrieval, "products": product_retrieval}
        partial: dict[str, Any] = {}
        available = 0
        degraded = False
        any_hits = False
        for name, retrieval in sources.items():
            if retrieval is None:
                partial[name] = {"status": "unavailable", "reason": "no_published_index", "hits": 0}
                continue
            status = retrieval["status"]
            source: dict[str, Any] = {
                "status": status,
                "reason": retrieval.get("fallback_reason") or retrieval.get("code"),
                "hits": len(retrieval.get("hits") or []),
            }
            if retrieval.get("code"):
                # The cause is kept next to the status: "unavailable" alone does
                # not say whether the index is missing, stale or broken.
                source["code"] = retrieval["code"]
            if retrieval.get("message"):
                source["message"] = retrieval["message"]
            partial[name] = source
            if status == "unavailable":
                continue
            available += 1
            if status == "degraded":
                degraded = True
            if retrieval.get("hits"):
                any_hits = True

        if available == 0:
            # Neither half ran. Nothing was searched, so this is a failed read and
            # never an empty result: "we could not look" is not "there is nothing".
            failed: dict[str, Any] = {
                "kind": "recommend",
                "status": STATUS_FAILED,
                "query": query,
                **self._retrieval_evidence(dish_retrieval or product_retrieval),
                "partial_sources": partial,
                "buildable_dishes": [],
                "sellable_products": [],
            }
            failed.setdefault("code", "INDEX_UNAVAILABLE")
            failed.setdefault("message", "检索索引不可用，本轮没有执行检索。")
            return failed

        if degraded or available < len(sources):
            # A partial or fallback answer: usable, but never presented as a
            # complete hybrid recommendation.
            overall, empty = "degraded", not any_hits
        elif any_hits:
            overall, empty = "ok", False
        else:
            # Only both-sources-ran-and-both-were-empty is a complete empty.
            overall, empty = "empty", True

        # Candidate metadata is carried whole — match_kind, evidence,
        # review_status, stock_verified, unknown_constraints — exactly as a lookup
        # carries it. Only the *overall* status is this read's own judgement about
        # the pair; everything else describes the source it came from.
        dishes = [_lookup_row("dish", hit) for hit in (dish_retrieval or {}).get("hits") or []]
        products = [_lookup_row("product", hit) for hit in (product_retrieval or {}).get("hits") or []]
        reasons = [entry.get("reason") for entry in partial.values() if entry.get("reason")]
        evidence = self._retrieval_evidence(dish_retrieval or product_retrieval)
        evidence.pop("code", None)
        evidence.pop("message", None)
        return {
            "kind": "recommend",
            "status": STATUS_COMPLETED,
            "query": query,
            "empty": empty,
            **evidence,
            "retrieval_status": overall,
            "fallback_reason": reasons[0] if reasons else None,
            "partial_sources": partial,
            "stock_verified": False,
            "note": (
                "按菜名/用途标签匹配到的菜谱，尚未校验是否配得齐，也不是库存或价格承诺；"
                "只有生成清单时才会校验真实商品与库存。"
            ),
            "buildable_dishes": [d for d in dishes if d.get("dish_id")],
            "sellable_products": [p for p in products if p.get("sku_id")],
        }

    def _dish_by_id(self, dish_id: str) -> dict[str, Any] | None:
        from app.services.template_matcher import get_template_by_id

        return get_template_by_id(self.db, dish_id)


def _legacy_rows(search: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of a pre-index dish search — only ever the ones that matched."""
    return list(search.get("candidates") or []) if search.get("status") == "ok" else []


def _applied_exclusions(excluded: list[str]) -> dict[str, Any]:
    """Which exclusions a pre-index read really applied.

    The indexed route reports its own ``filters_applied``; the pre-index path
    reports the same field from the same merged list, so a caller can tell what
    was filtered on either route instead of having to assume nothing was.
    """
    return {"excluded_ingredient_ids": sorted({str(x) for x in excluded if str(x).strip()})}


def _drop_excluded_products(
    rows: list[dict[str, Any]], excluded: list[str] | None
) -> list[dict[str, Any]]:
    """Hard exclusion on the pre-index product path.

    A product declaring an excluded ingredient is dropped, exactly as the plan
    builder drops it. The rule is not skipped just because no index is deployed,
    and the ingredient synonyms the dish search already knows are honoured here
    too so both routes agree on what "不要花生" excludes.
    """
    blocked = expand_ingredient_terms(excluded)
    if not blocked:
        return list(rows)
    return [row for row in rows if not (set(row.get("ingredient_ids") or []) & blocked)]


def _lookup_row(kind: str, hit: dict[str, Any]) -> dict[str, Any]:
    """Reshape one retrieval hit into the row shape the candidate list expects.

    References are still allocated by ``CandidateSet`` — the retrieval service
    never mints one.
    """
    if kind == "dish":
        return {
            "dish_id": hit.get("target_id"),
            "name": hit.get("name"),
            "match_kind": hit.get("match_kind"),
            "evidence": hit.get("evidence"),
            "review_status": hit.get("review_status"),
            "stock_verified": hit.get("stock_verified"),
            "unknown_constraints": hit.get("unknown_constraints"),
        }
    return {
        "sku_id": hit.get("target_id"),
        "name": hit.get("name"),
        "match_kind": hit.get("match_kind"),
        "evidence": hit.get("evidence"),
        "review_status": hit.get("review_status"),
        "stock_verified": hit.get("stock_verified"),
        "unknown_constraints": hit.get("unknown_constraints"),
    }


__all__ = ["MAX_LOOKUP_ROWS", "REASON_DEADLINE", "ReadTools"]

"""The one retrieval service: exact, lexical, vector, RRF, and degradation.

This is not a second agent and not a second decision chain. It answers "which
documents are relevant" and nothing else: it never writes a plan, never touches
the cart, never authors an answer, and never resolves a reference — the model
references candidates through the turn's own ``CandidateSet``.

Route order, and why:

1. **Exact / registered alias wins outright and needs no network.** If the
   shopper named a dish, they named it; asking an embedding model to confirm is
   slower and strictly worse. A naming match that collides with a hard
   constraint is reported as a conflict — never quietly swapped for a similar dish.
2. **Everything else runs the lexical route and the vector route in parallel**
   and fuses them with RRF. A fuzzy name match is a *sub-signal inside the
   lexical route*, not a third route: it must not short-circuit retrieval, and
   it must not be counted twice.
3. **Hard filters run before recall**, from the real ``ValidationContext``.
   Negation is never delegated to an embedding: "不要花生" is a structured
   exclusion, not something a vector is asked to understand.

Degradation is reported, never hidden. Which route ran, why the other one did
not, and what was filtered are all separate fields, because a single boolean
cannot tell an operator whether the store is broken or the query was empty.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.llm.embedding import (
    EmbeddingContract,
    EmbeddingUnavailable,
    validate_and_normalize,
)
from app.services.retrieval_index import (
    IndexUnavailable,
    LoadedIndex,
    embedding_contract_key,
    load_index,
)
from app.services.retrieval_projection import DOC_DISH, DOC_SKU, build_dictionary
from app.services.template_matcher import normalize_text
from app.services.validation_context import ValidationContext

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

MODE_HYBRID = "hybrid"
MODE_LEXICAL = "lexical"

#: Each route contributes its top N; RRF fuses; the fused list is then verified
#: and topped up until ``limit`` hits survive. N is deliberately larger than
#: ``limit`` — taking 5 and then checking stock can lose all 5 while ranks 6-20
#: were fine.
ROUTE_TOP_N = 20
#: Suggested in the plan, not copied from any vector database default.
RRF_K = 60

#: RapidFuzz is a *sub*-signal of the lexical route. Weight, not a parallel route.
FUZZY_SUB_SIGNAL_WEIGHT = 0.4
#: A name this close is offered as a fuzzy candidate even if FTS5 missed it.
FUZZY_ADMIT_RATIO = 72.0
#: A vector-only hit below this cosine is not offered at all. Nearest neighbour
#: always exists; a low-similarity neighbour is not an answer.
#:
#: This value is an **uncalibrated** starting point, not a threshold derived from
#: the annotated set. It has never been fitted to real vectors, because no real
#: embedding model has been run here. Do not cite it as evidence that the
#: no-answer behaviour is calibrated.
MIN_VECTOR_COSINE = 0.35

MAX_EVIDENCE_ITEMS = 3
MAX_EVIDENCE_CHARS = 120

#: Unknown dimensions we must admit rather than claim. Matched against the query
#: text; each one becomes an explicit ``unknown_constraints`` entry.
_UNKNOWN_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("taste", ("辣", "清淡", "口味", "酸甜", "咸", "香")),
    ("cook_minutes", ("分钟", "快手", "简单", "复杂", "耗时")),
    ("allergens", ("过敏", "花生", "坚果", "麸质", "乳", "忌口")),
    ("nutrition", ("热量", "卡路里", "营养", "蛋白", "低脂", "低糖", "糖含量", "含糖量")),
)

#: Query vectors are cached per process, keyed by the *whole* embedding contract
#: plus the exact query text. A cache keyed on model name alone would hand back a
#: vector produced under a different instruction or dimension.
_QUERY_VECTOR_CACHE: dict[str, list[float]] = {}
_QUERY_VECTOR_CACHE_LIMIT = 512


def cache_key(contract: dict[str, Any], kind: str, query: str) -> str:
    return f"{embedding_contract_key(contract)}|{kind}|{query}"


def _cache_get(key: str) -> list[float] | None:
    return _QUERY_VECTOR_CACHE.get(key)


def _cache_put(key: str, vector: list[float]) -> None:
    if len(_QUERY_VECTOR_CACHE) >= _QUERY_VECTOR_CACHE_LIMIT:
        _QUERY_VECTOR_CACHE.clear()
    _QUERY_VECTOR_CACHE[key] = vector


def clear_query_cache() -> None:
    _QUERY_VECTOR_CACHE.clear()


# ------------------------------------------------------------------- filters


@dataclass(frozen=True)
class RetrievalFilters:
    """Hard, structured constraints. Built from the real Requirements/context.

    Nothing here is inferred from the query text, and nothing here is a vector.
    An exclusion the shopper stated is a filter; a *similarity* is not.
    """

    excluded_ingredient_ids: frozenset[str] = frozenset()
    people: int | None = None
    budget_fen: int | None = None
    specification: dict[str, Any] = field(default_factory=dict)
    pantry_confirmed: tuple[str, ...] = ()
    delivery_deadline_minutes: int | None = None

    @classmethod
    def none(cls) -> "RetrievalFilters":
        return cls()

    @classmethod
    def from_context(
        cls,
        context: ValidationContext | None,
        *,
        ingredient_aliases: dict[str, str] | None = None,
    ) -> "RetrievalFilters":
        if context is None:
            return cls()
        return cls(
            excluded_ingredient_ids=frozenset(
                _canonical_ids(context.excluded_ingredients or [], ingredient_aliases)
            ),
            people=context.people,
            budget_fen=context.budget_fen,
            specification=dict(context.specification or {}),
            pantry_confirmed=tuple(context.pantry_confirmed or ()),
            delivery_deadline_minutes=context.delivery_deadline_minutes,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "excluded_ingredient_ids": sorted(self.excluded_ingredient_ids),
            "people": self.people,
            "budget_fen": self.budget_fen,
            "specification": dict(self.specification),
            "pantry_confirmed": list(self.pantry_confirmed),
            "delivery_deadline_minutes": self.delivery_deadline_minutes,
        }


def _canonical_ids(values: list[str], aliases: dict[str, str] | None = None) -> list[str]:
    """Resolve an exclusion to canonical ids *and* keep the raw term.

    The shopper says "不要花生"; the catalog says ``peanut``. Both forms are kept
    so a dish declaring either spelling is filtered.

    The alias map comes from the **index**, which froze it at build time. The
    request path must not re-read the mutable fixture: an exclusion resolved
    against a newer dictionary than the one the documents were built from would
    filter on a vocabulary the index does not use.
    """
    resolved: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        resolved.append(text)
        if aliases:
            canonical = aliases.get(text)
            if canonical:
                resolved.append(canonical)
    return list(dict.fromkeys(resolved))


def _dish_conflicts(payload: dict[str, Any], filters: RetrievalFilters) -> list[str]:
    if not filters.excluded_ingredient_ids:
        return []
    declared = set(payload.get("all_ingredient_ids") or [])
    declared |= {str(p) for p in payload.get("pantry_items") or []}
    return sorted(declared.intersection(filters.excluded_ingredient_ids))


def _sku_conflicts(payload: dict[str, Any], filters: RetrievalFilters) -> list[str]:
    if not filters.excluded_ingredient_ids:
        return []
    declared = set(payload.get("declared_ingredient_ids") or [])
    declared |= set(payload.get("verified_mapping_relations") or [])
    return sorted(declared.intersection(filters.excluded_ingredient_ids))


# ---------------------------------------------------------------------- hits


@dataclass
class RetrievalHit:
    kind: str
    target_id: str
    name: str
    match_kind: str
    evidence: list[str]
    review_status: str
    stock_verified: bool
    unknown_constraints: list[str]
    score: float = 0.0
    routes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target_id": self.target_id,
            "name": self.name,
            "match_kind": self.match_kind,
            "evidence": self.evidence[:MAX_EVIDENCE_ITEMS],
            "review_status": self.review_status,
            "stock_verified": self.stock_verified,
            "unknown_constraints": list(self.unknown_constraints),
        }


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text[:MAX_EVIDENCE_CHARS]


def _dish_evidence(
    doc: dict[str, Any],
    payload: dict[str, Any],
    route: str,
    names: dict[str, str] | None = None,
) -> list[str]:
    names = names or {}
    evidence = [_clip(f"菜名：{doc.get('name') or ''}")]
    if payload.get("aliases"):
        evidence.append(_clip("别名：" + "、".join(str(a) for a in payload["aliases"][:4])))
    main = [
        names.get(str(i)) or str(i)
        for i in payload.get("required_ingredient_ids") or []
    ]
    if main:
        evidence.append(_clip("主料：" + "、".join(main[:6])))
    evidence.append(_clip(f"匹配方式：{route}"))
    return evidence[:MAX_EVIDENCE_ITEMS]


def _sku_evidence(doc: dict[str, Any], payload: dict[str, Any], route: str) -> list[str]:
    evidence = [_clip(f"商品：{doc.get('name') or ''}")]
    facts = []
    spec_qty = payload.get("spec_quantity")
    spec_unit = payload.get("spec_unit")
    if spec_qty is not None and spec_unit:
        facts.append(f"规格：{spec_qty}{spec_unit}")
    if payload.get("category_id"):
        facts.append(f"品类：{payload['category_id']}")
    if payload.get("product_type"):
        facts.append(f"商品类型：{payload['product_type']}")
    if facts:
        evidence.append(_clip("；".join(facts)))
    if payload.get("usage_tags"):
        evidence.append(_clip("用途：" + "、".join(str(t) for t in payload["usage_tags"])))
    evidence.append(_clip(f"匹配方式：{route}"))
    return evidence[:MAX_EVIDENCE_ITEMS]


def _unknown_constraints(query: str, filters: RetrievalFilters, kind: str) -> list[str]:
    """Dimensions we are not able to verify, stated as unknown.

    The data carries no taste, cook time, nutrition or allergen facts, so a query
    that asks about one is answered with an explicit unknown instead of an
    implied "yes".
    """
    unknown: list[str] = []
    for name, signals in _UNKNOWN_SIGNALS:
        if any(signal in query for signal in signals):
            unknown.append(name)
    if kind == DOC_DISH and filters.budget_fen is not None:
        # Budget is a whole-basket property; retrieval does not price one.
        unknown.append("budget")
    if kind == DOC_DISH and filters.specification:
        unknown.append("specification")
    return list(dict.fromkeys(unknown))


# ------------------------------------------------------------------- service


class RetrievalService:
    """Read-only retrieval over one published index version."""

    def __init__(
        self,
        db: Session,
        *,
        store_id: str,
        delivery_zone_id: str,
        index_root: str | Path | None = None,
        mode: str | None = None,
        embedding_provider: Any | None = None,
        index: LoadedIndex | None = None,
        verify_live: bool = True,
        clock: Any = None,
    ):
        self.db = db
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        resolved_root = _configured_index_root()
        #: Whether retrieval is *deployed* here. An empty configuration means the
        #: product runs its pre-index lookup path; it is not a failure. An
        #: explicitly configured root that has no usable index is a failure and
        #: must never be disguised as a successful lookup.
        self.index_configured = bool(index_root) or resolved_root is not None
        self.index_root = Path(index_root) if index_root else (resolved_root or Path("."))
        self.mode = (mode or _default_mode()).strip().lower()
        self.embedding_provider = embedding_provider
        self._index = index
        self.verify_live = verify_live
        self._clock = clock or time.monotonic
        self._dictionary: dict[str, Any] | None = None
        #: Whether the index and the runtime database were compared yet, and the
        #: answer. One comparison per service instance, not one per request.
        self._corpus_checked: bool | None = None
        #: Whether application settings were already consulted for an embedding
        #: provider. Consulted once per service instance, never per query.
        self._provider_resolved = False
        #: The real ``ValidationContext`` of the search in flight, used for the
        #: business rules the context itself owns (specification, exclusions).
        self._context: ValidationContext | None = None

    # ------------------------------------------------------------- index load

    def _load(self) -> LoadedIndex | None:
        if self._index is not None:
            return self._index
        try:
            self._index = load_index(self.index_root)
        except (IndexUnavailable, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
            logger.info("retrieval index unavailable: %s", type(exc).__name__)
            return None
        return self._index

    def unavailable_result(self, code: str, message: str) -> dict[str, Any]:
        """A reported failure, in the same shape as a successful search result.

        Used by the read port when retrieval is deployed but cannot answer. It
        keeps the interface uniform so a caller cannot mistake "the index is
        missing" for "nothing matched".
        """
        return {
            "status": STATUS_UNAVAILABLE,
            "retrieval_mode": self.mode,
            "fallback_reason": None,
            "index_version": None,
            "filters_applied": {},
            "hits": [],
            "empty": True,
            "code": code,
            "message": message,
        }

    def describes_runtime_db(self) -> bool:
        """Whether the published index was built from the corpus this session serves.

        An index built from one snapshot must never answer for a different
        database: its document ids, names and evidence all describe the other
        corpus. The check is two counts, not a whole-corpus hash, and it is done
        once per service instance — never per request in a loop.

        A mismatch is not "the index is broken"; it is "this index is not this
        database's index", and the caller decides what to do about it.
        """
        index = self._load()
        if index is None:
            return False
        if self._corpus_checked is None:
            self._corpus_checked = self._counts_match(index)
        return self._corpus_checked

    def _counts_match(self, index: LoadedIndex) -> bool:
        from sqlalchemy import func

        from app.models.catalog import CatalogProduct, PurchaseTemplate
        from app.services.retrieval_projection import DISH_SOURCE

        counts = index.manifest.get("counts") or {}
        with self.db.no_autoflush:
            try:
                dishes = (
                    self.db.query(func.count(PurchaseTemplate.template_id))
                    .filter(PurchaseTemplate.source == DISH_SOURCE)
                    .scalar()
                )
                skus = (
                    self.db.query(func.count(CatalogProduct.sku_id))
                    .filter(CatalogProduct.review_status == "approved")
                    .scalar()
                )
            except Exception:  # pragma: no cover - an unreadable DB is its own failure
                logger.exception("could not compare the index against the runtime database")
                return False
        expected_dishes = counts.get("dishes")
        expected_skus = counts.get("skus")
        if expected_dishes is None or expected_skus is None:
            return False
        if int(dishes or 0) != int(expected_dishes) or int(skus or 0) != int(expected_skus):
            logger.info(
                "retrieval index %s describes %s dishes / %s skus but this database has "
                "%s / %s; not answering from it",
                index.version, expected_dishes, expected_skus, dishes, skus,
            )
            return False
        return True

    def _dictionary_for(self, index: LoadedIndex) -> dict[str, Any]:
        """The dictionary must come from the same snapshot as the documents.

        It is read out of the index, which froze it at build time. Rebuilding it
        from the fixture on the request path would let the vocabulary drift away
        from the documents it segments.
        """
        if self._dictionary is None:
            frozen = index.dictionary()
            if frozen is not None:
                self._dictionary = frozen
                return self._dictionary
            raise IndexUnavailable("INDEX_STALE", "frozen dictionary missing; rebuild required")
        return self._dictionary

    # ------------------------------------------------------------ public API

    def search_dishes(
        self, query: str, *, context: ValidationContext | None = None, limit: int = 5
    ) -> dict[str, Any]:
        return self._search(query, kind=DOC_DISH, context=context, limit=limit)

    def search_products(
        self, query: str, *, context: ValidationContext | None = None, limit: int = 5
    ) -> dict[str, Any]:
        return self._search(query, kind=DOC_SKU, context=context, limit=limit)

    # -------------------------------------------------------------- internals

    def _search(
        self, query: str, *, kind: str, context: ValidationContext | None, limit: int,
    ) -> dict[str, Any]:
        # Live facts are cached for this search only, never across requests.
        self._live_products = None
        self._live_delivery = None
        self._stale_ids = []
        try:
            with self.db.no_autoflush:
                result = self._search_impl(query, kind=kind, context=context, limit=max(0, min(limit, 5)))
            if self._stale_ids:
                result["stale_document_ids"] = list(dict.fromkeys(self._stale_ids))
                result["index_update_required"] = True
            return result
        except (IndexUnavailable, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            return self.unavailable_result(getattr(exc, "code", "INDEX_BROKEN"),
                                           "检索数据暂不可用；本轮未完成检索。")

    def _search_impl(
        self,
        query: str,
        *,
        kind: str,
        context: ValidationContext | None,
        limit: int,
    ) -> dict[str, Any]:
        self._context = context
        if self.mode not in (MODE_LEXICAL, MODE_HYBRID):
            return self.unavailable_result("INVALID_RETRIEVAL_MODE", "检索模式配置无效。")
        if limit == 0:
            return {**self.unavailable_result("EMPTY_LIMIT", "未请求候选。"), "status": STATUS_EMPTY}
        index = self._load()
        filters = RetrievalFilters.from_context(
            context,
            ingredient_aliases=(index.ingredient_maps()["aliases"] if index is not None else None),
        )
        base: dict[str, Any] = {
            "status": STATUS_UNAVAILABLE,
            "retrieval_mode": self.mode,
            "fallback_reason": None,
            "index_version": None,
            "filters_applied": filters.as_dict(),
            "unknown_constraints": _unknown_constraints(query, filters, kind),
            "hits": [],
            "empty": True,
        }
        if index is None or not query.strip():
            if index is None:
                base["code"] = (
                    _unavailable_code(self.index_root)
                    if self.index_configured
                    else "RETRIEVAL_NOT_CONFIGURED"
                )
                base["message"] = "检索索引不可用，本轮没有执行检索。"
            else:
                base["code"] = "EMPTY_QUERY"
                base["message"] = "检索词为空，没有执行检索。"
            return base
        base["index_version"] = index.version
        dictionary = self._dictionary_for(index)

        # 1. Exact / registered alias. No embedding, no network.
        exact = self._exact_hit(index, query, kind=kind)
        dropped_exact: dict[str, Any] | None = None
        if exact is not None:
            verified, drop, constraint_fields = self._verify(
                exact["doc"], kind=kind, filters=filters
            )
            if drop:
                if constraint_fields:
                    base["status"] = STATUS_OK
                    base["match_kind"] = exact["match_kind"]
                    base["conflict"] = {
                        "code": "CONSTRAINT_CONFLICT",
                        "target_id": exact["doc"]["target_id"],
                        "name": exact["doc"]["name"],
                        "constraint_fields": constraint_fields,
                        "message": "这件商品不符合你提出的小包装要求，不能用其他商品替代你点名的商品。",
                    }
                    return base
                # The shopper named this dish and the live store no longer
                # matches the indexed document. It is not resurrected from the
                # fixture, and the answer is **not** quietly filled with a
                # similarly named dish: that is exactly the silent substitution
                # the design forbids. The turn is told the named target is gone.
                dropped_exact = {
                    "target_id": str(exact["doc"]["target_id"]),
                    "name": str(exact["doc"]["name"]),
                    "code": "STALE_EXACT_MATCH",
                    "message": (
                        "这道菜在你点名之后已经变更或下架，本轮没有用相近的菜替代它。"
                        "请确认要哪一道，或重新查询。"
                    ),
                }
                exact = None
        if exact is not None:
            conflicts = self._conflicts_for(kind, exact["payload"], filters)
            if conflicts:
                base["status"] = STATUS_OK
                base["match_kind"] = exact["match_kind"]
                base["conflict"] = {
                    "code": "CONSTRAINT_CONFLICT",
                    "target_id": exact["doc"]["target_id"],
                    "name": exact["doc"]["name"],
                    "conflicting_ingredients": conflicts,
                    "message": (
                        "这道菜需要你已排除的食材，不能替换成别的菜。"
                        "请取消排除条件，或明确改选另一道菜。"
                    ),
                }
                return base
            hit = self._to_hit(
                index, exact["doc"], kind=kind, match_kind=exact["match_kind"],
                filters=filters, query=query, routes=("exact",), verified=verified,
            )
            base["status"] = STATUS_OK
            base["hits"] = [hit.as_dict()] if hit else []
            base["empty"] = not base["hits"]
            base["match_kind"] = exact["match_kind"]
            return base

        if dropped_exact is not None:
            base["status"] = STATUS_EMPTY
            base["empty"] = True
            base["dropped_exact_match"] = dropped_exact
            return base

        # 2. Lexical + vector, filtered before recall.
        pool = self._candidate_pool(index, kind=kind)
        pool = [
            doc
            for doc in pool
            if not self._conflicts_for(kind, doc["payload"], filters)
        ]
        if not pool:
            base["status"] = STATUS_EMPTY
            base["empty"] = True
            return base

        try:
            lexical = self._lexical_route(index, dictionary, query, kind=kind, pool=pool)
        except IndexUnavailable as exc:
            # A corrupt lexical table is a broken index, not an empty corpus.
            base["code"] = exc.code
            base["message"] = "检索索引损坏，本轮没有执行检索。"
            return base
        fused, degraded_reason = self._vector_route_and_fuse(index, query, lexical, pool)

        if degraded_reason and degraded_reason in ("index_stale", "index_broken", "index_missing"):
            # A structurally broken or incompatible corpus is not a degradation:
            # there is nothing healthy left to answer from.
            base["code"] = degraded_reason.upper()
            base["message"] = "检索索引与当前语料不兼容或已损坏，本轮没有执行检索。"
            return base
        if degraded_reason:
            base["status"] = STATUS_DEGRADED
            base["retrieval_mode"] = MODE_LEXICAL
            base["fallback_reason"] = degraded_reason
        else:
            base["status"] = STATUS_OK

        ordered = self._verify_and_fill(index, fused, kind=kind, filters=filters,
                                        query=query, limit=limit)
        if not ordered and base["status"] == STATUS_OK:
            base["status"] = STATUS_EMPTY
        base["hits"] = [hit.as_dict() for hit in ordered]
        base["empty"] = not ordered
        return base

    # ------------------------------------------------------------- exact route

    def _exact_hit(self, index: LoadedIndex, query: str, *, kind: str) -> dict[str, Any] | None:
        normalized = normalize_text(query)
        if not normalized:
            return None
        matches = []
        for doc in self._candidate_pool(index, kind=kind):
            # The stable id is a registered name too: "dish-fanqie-chao-dan" names
            # exactly one dish, and matching it is deterministic.
            if str(doc["target_id"]).lower() == query.strip().lower():
                return {"doc": doc, "match_kind": "exact", "payload": doc["payload"]}
            name_norm = normalize_text(str(doc["name"]))
            if name_norm and name_norm == normalized:
                matches.append({"doc": doc, "match_kind": "exact", "payload": doc["payload"]})
                continue
            for alias in doc["payload"].get("aliases") or []:
                alias_norm = normalize_text(str(alias))
                if alias_norm and alias_norm == normalized:
                    matches.append({"doc": doc, "match_kind": "alias", "payload": doc["payload"]})
                    break
        return matches[0] if len(matches) == 1 else None

    # ----------------------------------------------------------- lexical route

    def _lexical_route(
        self,
        index: LoadedIndex,
        dictionary: dict[str, Any],
        query: str,
        *,
        kind: str,
        pool: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """FTS5 BM25, with RapidFuzz blended in as a sub-signal of this route."""
        allowed = {doc["doc_id"] for doc in pool}
        scores: dict[str, float] = {}
        for doc_id, bm25_score in index.lexical_search(
            query, dictionary, limit=ROUTE_TOP_N * 2, allowed_ids=allowed
        ):
            scores[doc_id] = bm25_score

        by_id = {doc["doc_id"]: doc for doc in pool}
        for doc_id, fuzzy in self._fuzzy_scores(query, pool):
            if fuzzy < FUZZY_ADMIT_RATIO:
                continue
            # Sub-signal: it adds to the lexical score, it never becomes a route.
            scores[doc_id] = scores.get(doc_id, 0.0) + FUZZY_SUB_SIGNAL_WEIGHT * (fuzzy / 100.0)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:ROUTE_TOP_N]
        return [
            {"doc": by_id[doc_id], "route": "lexical", "score": score, "fuzzy": _fuzzy_of(query, by_id[doc_id])}
            for doc_id, score in ranked
        ]

    def _fuzzy_scores(self, query: str, pool: list[dict[str, Any]]) -> list[tuple[str, float]]:
        from rapidfuzz import fuzz

        normalized = normalize_text(query)
        if not normalized:
            return []
        scored: list[tuple[str, float]] = []
        for doc in pool:
            best = 0.0
            for label in [doc["name"], *(doc["payload"].get("aliases") or [])]:
                label_norm = normalize_text(str(label))
                if not label_norm:
                    continue
                best = max(best, float(fuzz.ratio(normalized, label_norm)))
            scored.append((doc["doc_id"], best))
        return scored

    # ------------------------------------------------------------ vector route

    def _vector_route_and_fuse(
        self,
        index: LoadedIndex,
        query: str,
        lexical: list[dict[str, Any]],
        pool: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return the fused ranking and, when the vector route could not run, why."""
        if self.mode == MODE_LEXICAL:
            # A deliberate deployment mode, not a failure. Reported as ok/lexical.
            return self._fuse(lexical, []), None
        try:
            if not index.has_vectors():
                return self._fuse(lexical, []), "vector_index_missing"
        except sqlite3.Error:
            return self._fuse(lexical, []), "vector_index_broken"
        provider = self._provider()
        if provider is None:
            return self._fuse(lexical, []), "embedding_provider_not_configured"

        contract = index.embedding_contract or {}
        try:
            self._require_contract_match(contract)
            vector = self._query_vector(index, query)
        except (EmbeddingUnavailable, ValueError) as exc:
            reason = getattr(exc, "code", None) or "embedding_failed"
            return self._fuse(lexical, []), str(reason).lower()

        allowed = {doc["doc_id"] for doc in pool}
        by_id = {doc["doc_id"]: doc for doc in pool}
        semantic: list[dict[str, Any]] = []
        try:
            ranked = index.vector_search(vector, limit=ROUTE_TOP_N * 2, allowed_ids=allowed)
        except (IndexUnavailable, sqlite3.Error, ValueError, OverflowError):
            return self._fuse(lexical, []), "vector_index_broken"
        for doc_id, score in ranked:
            if score < MIN_VECTOR_COSINE:
                continue
            semantic.append({"doc": by_id[doc_id], "route": "vector", "score": score})
            if len(semantic) >= ROUTE_TOP_N:
                break
        del contract
        return self._fuse(lexical, semantic), None

    def _provider(self) -> Any | None:
        """The configured embedding provider, built once, or ``None``.

        Nothing is looked up per request beyond the first: the provider is
        stateless apart from its HTTP client settings. Use the same resolved
        application settings as chat; a value in .env must not be ignored just
        because it was not also exported into the process environment.
        """
        if self.embedding_provider is not None:
            return self.embedding_provider
        if self._provider_resolved:
            return None
        self._provider_resolved = True
        try:
            from app.llm.embedding import HttpEmbeddingProvider
            from app.core.config import get_settings

            self.embedding_provider = HttpEmbeddingProvider.from_settings(get_settings())
        except EmbeddingUnavailable as exc:
            logger.info("vector route unavailable: %s", exc.message)
            self.embedding_provider = None
        return self.embedding_provider

    def _require_contract_match(self, index_contract: dict[str, Any]) -> None:
        """The provider's contract must be the index's contract.

        A provider configured for another model, revision, dimension or
        instruction produces vectors that are not comparable with the stored
        ones. Scoring them anyway would return confident nonsense, so the vector
        route is refused and the reason is reported.
        """
        provider = self._provider()
        provider_contract = getattr(provider, "contract", None)
        if provider_contract is None:
            return
        provider_dict = provider_contract.as_dict()
        if embedding_contract_key(provider_dict) != embedding_contract_key(index_contract):
            raise EmbeddingUnavailable(
                "EMBEDDING_CONTRACT_MISMATCH",
                "the configured embedding provider does not match the index's embedding contract",
            )

    def _query_vector(self, index: LoadedIndex, query: str) -> list[float]:
        contract_dict = index.embedding_contract or {}
        key = cache_key(contract_dict, "query", query)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        contract = EmbeddingContract(
            model=str(contract_dict.get("model") or ""),
            revision=str(contract_dict.get("revision") or ""),
            dimension=int(contract_dict.get("dimension") or 0),
            normalize=bool(contract_dict.get("normalize", True)),
            dtype=str(contract_dict.get("dtype") or "float32"),
            query_instruction=str(contract_dict.get("query_instruction") or ""),
            document_instruction=contract_dict.get("document_instruction"),
        )
        # The instruction is applied by the provider, exactly once. Prefixing it
        # here as well would send "query: query: ..." to the endpoint.
        vectors = self.embedding_provider.embed([query], kind="query")
        if not vectors:
            raise EmbeddingUnavailable("EMBEDDING_EMPTY_RESPONSE", "provider returned no vector")
        # Same contract enforcement as the offline build: the declared dimension
        # and finite values are mandatory, and the result is unit-normalized so
        # an exact cosine is a dot product.
        checked = validate_and_normalize(vectors, contract)
        vector = checked[0]
        _cache_put(key, vector)
        return vector

    def _fuse(
        self, lexical: list[dict[str, Any]], semantic: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Reciprocal rank fusion over the two routes, one rank list each."""
        fused: dict[str, dict[str, Any]] = {}
        for route_name, ranked in (("lexical", lexical), ("vector", semantic)):
            for rank, entry in enumerate(ranked, start=1):
                doc_id = entry["doc"]["doc_id"]
                bucket = fused.setdefault(
                    doc_id, {"doc": entry["doc"], "score": 0.0, "routes": set(), "raw": {}}
                )
                bucket["score"] += 1.0 / (RRF_K + rank)
                bucket["routes"].add(route_name)
                bucket["raw"][route_name] = entry["score"]
        ordered = sorted(fused.values(), key=lambda item: item["score"], reverse=True)
        return ordered

    # --------------------------------------------------------------- filters

    def _conflicts_for(self, kind: str, payload: dict[str, Any], filters: RetrievalFilters) -> list[str]:
        if kind == DOC_DISH:
            return _dish_conflicts(payload, filters)
        return _sku_conflicts(payload, filters)

    def _candidate_pool(self, index: LoadedIndex, *, kind: str) -> list[dict[str, Any]]:
        rows = index.connection().execute(
            "SELECT doc_id, kind, target_id, name, text, payload_json, static_hash "
            "FROM docs WHERE kind = ?",
            (kind,),
        ).fetchall()
        return [
            {
                "doc_id": row["doc_id"],
                "kind": row["kind"],
                "target_id": row["target_id"],
                "name": row["name"],
                "text": row["text"],
                "payload": _payload(row),
                "static_hash": row["static_hash"],
            }
            for row in rows
        ]

    # ------------------------------------------------------- live verification

    def _verify_and_fill(
        self,
        index: LoadedIndex,
        fused: list[dict[str, Any]],
        *,
        kind: str,
        filters: RetrievalFilters,
        query: str,
        limit: int,
    ) -> list[RetrievalHit]:
        """Verify against live business data and top up until ``limit`` survive.

        A fused list longer than ``limit`` exists for exactly this reason: the
        top five may all be out of stock, and rank six may not be.
        """
        hits: list[RetrievalHit] = []
        for entry in fused:
            if len(hits) >= limit:
                break
            routes = tuple(sorted(entry["routes"]))
            match_kind = _match_kind(routes)
            verified, drop, _constraint_fields = self._verify(
                entry["doc"], kind=kind, filters=filters
            )
            if drop:
                # A document the live store no longer has, no longer sells, or
                # can no longer build is dropped rather than shown with a caveat.
                continue
            hit = self._to_hit(
                index,
                entry["doc"],
                kind=kind,
                match_kind=match_kind,
                filters=filters,
                query=query,
                routes=routes,
                verified=verified,
            )
            if hit is None:
                continue
            hits.append(hit)
        return hits

    def _verify(
        self, doc: dict[str, Any], *, kind: str, filters: RetrievalFilters
    ) -> tuple[bool | None, bool, list[str]]:
        """``(verified, stale, constraint_fields)`` against the live store.

        Dishes go through the existing plan builder — the same one that decides
        whether a plan can be generated, so retrieval never invents a second
        fulfillment rule and never claims more than the business layer does.
        Products check the live offer and available quantity.
        """
        if not self.verify_live:
            return None, False, []
        # The caller may have pending ORM mutations on this session. Reading live
        # facts must not flush them: a read-only port that commits someone else's
        # half-built write is not read-only.
        with self.db.no_autoflush:
            if self._live_document_is_stale(doc, kind=kind):
                self._stale_ids.append(doc["doc_id"])
                return None, True, []
            if kind == DOC_DISH:
                verified, drop = self._verify_dish(doc, filters)
                return verified, drop, []
            return self._verify_sku(doc)

    def _live_document_is_stale(self, doc: dict[str, Any], *, kind: str) -> bool:
        """Whether the live row still projects to exactly the indexed document.

        The comparison is the **whole static projection hash**, recomputed from
        the live row with the same code the build used. A renamed dish, a changed
        ingredient list, a changed product mapping and a changed usage tag all
        change that hash; comparing names alone would let every one of them keep
        evidence that describes a document the store no longer has.
        """
        index = self._load()
        if index is None:
            return True
        expected = index.doc_hashes.get(doc["doc_id"])
        if not expected:
            return True
        live = self._live_doc(doc["doc_id"], kind=kind)
        if live is None:
            return True
        if live.static_hash != expected:
            logger.info(
                "dropping stale %s: live projection hash differs from the indexed one",
                doc["doc_id"],
            )
            return True
        return False

    def _live_doc(self, doc_id: str, *, kind: str) -> Any | None:
        """Project one live row with the *build's* projector, so hashes compare."""
        from app.models.catalog import CatalogProduct, PurchaseTemplate
        from app.services.retrieval_projection import (
            project_dish_row,
            project_sku_row,
        )

        index = self._load()
        # The index's frozen ingredient names, not the fixture on disk: the hash
        # is only comparable if both sides were projected from the same names.
        frozen_names = index.ingredient_maps()["names"] if index is not None else None
        with self.db.no_autoflush:
            if kind == DOC_DISH:
                row = (
                    self.db.query(PurchaseTemplate)
                    .filter(PurchaseTemplate.template_id == str(doc_id).removeprefix("dish:"))
                    .one_or_none()
                )
                if row is None:
                    return None
                return project_dish_row(
                    {
                        "template_id": row.template_id,
                        "scenario": row.scenario,
                        "aliases_json": row.aliases_json,
                        "base_people": row.base_people,
                        "required_items": row.required_items,
                        "optional_items": row.optional_items,
                        "pantry_items": row.pantry_items,
                        "metadata_json": row.metadata_json,
                    },
                    frozen_names,
                )
            row = (
                self.db.query(CatalogProduct)
                .filter(CatalogProduct.sku_id == str(doc_id).removeprefix("sku:"))
                .one_or_none()
            )
            if row is None:
                return None
            return project_sku_row(
                {
                    "sku_id": row.sku_id,
                    "name": row.name,
                    "name_zh": row.name_zh,
                    "brand": row.brand,
                    "category_id": row.category_id,
                    "ingredient_ids": row.ingredient_ids,
                    "usage_tags": row.usage_tags,
                    "product_type": row.product_type,
                    "spec_quantity": row.spec_quantity,
                    "spec_unit": row.spec_unit,
                    "source": row.source,
                    "review_status": row.review_status,
                    "metadata_json": row.metadata_json,
                },
                frozen_names,
            )

    def _verify_dish(self, doc: dict[str, Any], filters: RetrievalFilters) -> tuple[bool | None, bool]:
        """A dish is always a *candidate*; it is never a fulfillment claim.

        ``stock_verified`` is therefore ``False`` for every dish, including one
        whose ingredients this store happens to be able to build right now.
        ``build_plan`` tolerates inferred mappings and a default pack size, so a
        successful build is not the strict tier the plan reserves for
        "verified fulfillable" — reporting ``True`` here would claim a check that
        was never performed.

        An unbuildable dish is still returned: it is what the shopper asked for,
        and the model is told plainly that it is not a stock promise.
        """
        # Live identity was checked above; fulfillment belongs to the planner.
        return False, False

    def _verify_sku(self, doc: dict[str, Any]) -> tuple[bool | None, bool, list[str]]:
        from app.services.catalog_service import CatalogService
        from app.services.delivery_service import DeliveryService
        if self._live_products is None:
            self._live_products = {
                str(item["sku_id"]): item
                for item in CatalogService(self.db, self.store_id).list_sellable_products()
            }
        if self._live_delivery is None:
            self._live_delivery = DeliveryService(self.db).get_quote(self.store_id, self.delivery_zone_id)
        delivery = self._live_delivery
        if not delivery.get("reachable"):
            return False, True, []
        deadline = self._context.delivery_deadline_minutes if self._context else None
        eta = delivery.get("eta_minutes")
        if deadline is not None and (eta is None or eta > deadline):
            return False, True, []
        product = self._live_products.get(str(doc["target_id"]))
        if product is None:
            # Not sellable at this store any more: a ghost row, dropped and logged.
            logger.info("dropping ghost sku %s: not sellable at this store", doc["doc_id"])
            return None, True, []
        if self._context is not None and not self._context.matches_spec(product):
            # A stated specification (for example "小包装") is a hard filter, and
            # it is answered by the same business rule the plan builder uses —
            # not by a second copy of the rule here.
            return False, True, ["specification"]
        available = product.get("available_qty")
        if available is None or product.get("price_fen") is None:
            return False, True, []
        if int(available) < 1:
            return False, True, []
        return True, False, []

    # ------------------------------------------------------------------- hits

    def _to_hit(
        self,
        index: LoadedIndex,
        doc: dict[str, Any],
        *,
        kind: str,
        match_kind: str,
        filters: RetrievalFilters,
        query: str,
        routes: tuple[str, ...],
        verified: bool | None,
    ) -> RetrievalHit | None:
        payload = doc["payload"]
        route_label = "/".join(routes) if routes else "exact"
        if kind == DOC_DISH:
            evidence = _dish_evidence(
                doc, payload, route_label, index.ingredient_maps()["names"]
            )
            review = str(payload.get("review_status") or "unreviewed")
        else:
            evidence = _sku_evidence(doc, payload, route_label)
            review = str(payload.get("review_status") or "approved")
        return RetrievalHit(
            kind=kind,
            target_id=str(doc["target_id"]),
            name=str(doc["name"]),
            match_kind=match_kind,
            evidence=evidence,
            review_status=review,
            # "We did not check" is not "verified". The three states stay apart.
            stock_verified=verified,
            unknown_constraints=_unknown_constraints(query, filters, kind),
            routes=routes,
        )


def _match_kind(routes: tuple[str, ...]) -> str:
    if routes == ("lexical",):
        return "lexical"
    if routes == ("vector",):
        return "semantic"
    return "fused"


def _payload(row: Any) -> dict[str, Any]:
    import json

    raw = row["payload_json"] if not isinstance(row, dict) else row.get("payload_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _fuzzy_of(query: str, doc: dict[str, Any]) -> float:
    from rapidfuzz import fuzz

    normalized = normalize_text(query)
    best = 0.0
    for label in [doc["name"], *(doc["payload"].get("aliases") or [])]:
        label_norm = normalize_text(str(label))
        if label_norm:
            best = max(best, float(fuzz.ratio(normalized, label_norm)))
    return best


def _unavailable_code(index_root: Path) -> str:
    try:
        from app.services.retrieval_index import read_pointer

        if read_pointer(index_root):
            return "INDEX_STALE"
    except Exception:  # pragma: no cover
        pass
    return "INDEX_UNAVAILABLE"


def _default_mode() -> str:
    from app.core.config import get_settings

    return str(getattr(get_settings(), "retrieval_mode", MODE_HYBRID) or MODE_HYBRID)


def _configured_index_root() -> Path | None:
    """The deployed index root, or ``None`` when retrieval is not deployed."""
    from app.core.config import get_settings

    settings = get_settings()
    configured = (getattr(settings, "retrieval_index_dir", "") or "").strip()
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_absolute() else settings.root_dir / path


__all__ = [
    "MIN_VECTOR_COSINE",
    "MODE_HYBRID",
    "MODE_LEXICAL",
    "ROUTE_TOP_N",
    "RRF_K",
    "RetrievalFilters",
    "RetrievalHit",
    "RetrievalService",
    "STATUS_DEGRADED",
    "STATUS_EMPTY",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "cache_key",
    "clear_query_cache",
]

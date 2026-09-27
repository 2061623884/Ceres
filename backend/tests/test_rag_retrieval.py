"""RAG S2/S3: projection, index, degradation, wiring and read-only guarantees.

Every vector in this file comes from a **mock provider defined in this file**. It
is deterministic and has no semantics worth reporting: these tests prove the
plumbing, the contract enforcement and the degradation paths. They are not
evidence that real semantic quality is met, and must never be reported as such.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.agent.protocol import CandidateSet, SemanticProtocolError
from app.llm.embedding import (
    EmbeddingContract,
    EmbeddingContractError,
    EmbeddingUnavailable,
    apply_instruction,
    validate_and_normalize,
)
from app.services.retrieval_index import (
    IndexUnavailable,
    load_index,
    read_pointer,
    validate_vector,
)
from app.services.retrieval_projection import build_projection, tokenize
from app.services.retrieval_service import (
    MODE_LEXICAL,
    RetrievalService,
    clear_query_cache,
)
from app.services.validation_context import ValidationContext

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_DB = ROOT / "verification" / "data-completion" / "candidate_runtime.sqlite3"

pytestmark = pytest.mark.skipif(
    not CANDIDATE_DB.is_file(), reason="S1 candidate snapshot is not present"
)

DIMENSION = 16


class MockEmbeddingProvider:
    """Deterministic, contract-shaped vectors. Not a semantic model."""

    def __init__(self, *, dimension: int = DIMENSION, fails: str | None = None):
        self.contract = EmbeddingContract(
            model="mock-embedding",
            revision="mock-rev-1",
            dimension=dimension,
            query_instruction="query: ",
        )
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self._fails = fails

    def embed(self, texts: list[str], *, kind: str) -> list[list[float]]:
        if self._fails:
            raise EmbeddingUnavailable(self._fails, "mock provider failure")
        self.calls.append((kind, tuple(texts)))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        from app.services.retrieval_index import normalize_vector

        raw = [0.0] * self.contract.dimension
        for token in tokenize(text, build_dictionary_for_tests()):
            # sha256, not hash(): Python salts str hashes per process, so an
            # index built in one run would not match a query in the next.
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            raw[int.from_bytes(digest[:4], "big") % self.contract.dimension] += 1.0
        if not any(raw):
            raw[0] = 1.0
        return validate_vector(
            normalize_vector(raw), dimension=self.contract.dimension
        )


_DICTIONARY: dict[str, Any] | None = None


def build_dictionary_for_tests() -> dict[str, Any]:
    global _DICTIONARY
    if _DICTIONARY is None:
        from app.services.retrieval_projection import build_dictionary, read_snapshot

        dishes, skus = read_snapshot(CANDIDATE_DB)
        _DICTIONARY = build_dictionary(dish_rows=dishes, sku_rows=skus)
    return _DICTIONARY


def build_index(root: Path, *, embed: bool = False, provider: Any | None = None) -> dict[str, Any]:
    """Build a private index for the test. Never touches the repo's index root."""
    from app.services.retrieval_index import (
        index_version_for,
        publish,
        write_index,
    )

    projection, dictionary = build_projection(CANDIDATE_DB, snapshot_label="test")
    contract = getattr(provider, "contract", None)
    contract_dict = contract.as_dict() if contract else None
    vectors = None
    if embed and provider is not None:
        vectors = {
            doc.doc_id: provider.embed([doc.text], kind="document")[0]
            for doc in projection.docs
        }
    version = index_version_for(projection, contract_dict)
    write_index(
        target_dir=root / version,
        projection=projection,
        dictionary=dictionary,
        embedding=contract_dict,
        vectors=vectors,
        audit_only={"candidate_db_path": str(CANDIDATE_DB), "test": True},
    )
    publish(root, version)
    return {"version": version, "projection": projection}


def service(db_session: Any, root: Path, *, mode: str = "hybrid", provider: Any | None = None,
            verify_live: bool = False) -> RetrievalService:
    clear_query_cache()
    return RetrievalService(
        db_session,
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
        index_root=root,
        mode=mode,
        embedding_provider=provider,
        verify_live=verify_live,
    )


# =========================================================== projection & index


def test_projection_separates_dishes_and_skus_without_inventing_metadata(tmp_path):
    projection, _dictionary = build_projection(CANDIDATE_DB, snapshot_label="test")
    dishes = projection.of_kind("dish")
    skus = projection.of_kind("sku")
    assert len(dishes) == 105
    assert skus, "the demo catalogue must produce SKU documents"
    assert all(doc.doc_id.startswith("dish:") for doc in dishes)
    assert all(doc.doc_id.startswith("sku:") for doc in skus)
    # Unknown attributes are absent, not fabricated.
    for doc in dishes:
        for invented in ("cook_minutes", "taste", "nutrition"):
            assert invented not in doc.text
    # Prices and stock are never part of a document.
    for doc in skus:
        assert "price" not in doc.text and "库存" not in doc.text


def test_every_document_has_its_own_static_hash(tmp_path):
    projection, _ = build_projection(CANDIDATE_DB, snapshot_label="test")
    assert set(projection.doc_hashes) == {doc.doc_id for doc in projection.docs}
    assert len(set(projection.doc_hashes.values())) > 1
    assert projection.snapshot_hash.startswith("sha256:")


def test_single_characters_are_controlled_by_the_frozen_dictionary():
    dictionary = build_dictionary_for_tests()
    assert "蛋" not in tokenize("蛋", {"version": "t", "terms": [], "by_length": {}, "single_chars": set()})
    # A registered single character is allowed through.
    registered = {
        "version": "t",
        "terms": ["蛋"],
        "by_length": {1: ["蛋"]},
        "single_chars": {"蛋"},
    }
    assert tokenize("蛋", registered) == ["蛋"]
    assert dictionary["single_chars"] is not None


def test_build_publishes_a_verified_manifest_and_atomic_pointer(tmp_path):
    result = build_index(tmp_path)
    index = load_index(tmp_path)
    try:
        assert index.version == result["version"]
        manifest = index.manifest
        assert manifest["counts"]["docs"] == manifest["counts"]["dishes"] + manifest["counts"]["skus"]
        assert manifest["text_template_version"] == "v1"
        assert manifest["lexical_tokenizer_version"] == "zh-dict-v1"
        assert manifest["projection_snapshot"]["dish_count"] == 105
        # The runtime path is audit information only: it cannot invalidate anything.
        assert "candidate_db_path" in manifest["audit_only"]
    finally:
        index.close()
    assert read_pointer(tmp_path) == result["version"]


def test_pointer_swap_keeps_the_previous_version_for_rollback(tmp_path):
    first = build_index(tmp_path)
    # Force a different version by changing the embedding contract.
    provider = MockEmbeddingProvider()
    second = build_index(tmp_path, embed=True, provider=provider)
    assert second["version"] != first["version"]
    assert read_pointer(tmp_path) == second["version"]
    assert (tmp_path / first["version"]).is_dir()
    assert (tmp_path / f"{first['version']}.prev").is_dir()


def test_a_failed_build_leaves_the_live_index_untouched(tmp_path):
    good = build_index(tmp_path)
    # A provider whose vectors violate the declared dimension must abort the
    # build before publish, not after.
    provider = MockEmbeddingProvider(dimension=DIMENSION + 1)
    with pytest.raises(ValueError):
        _build_with_bad_provider(tmp_path, provider)
    assert read_pointer(tmp_path) == good["version"]
    index = load_index(tmp_path)
    index.close()


def _build_with_bad_provider(root: Path, provider: Any) -> None:
    contract = provider.contract.as_dict()
    contract["dimension"] = DIMENSION  # contract says one thing, provider returns another
    from app.services.retrieval_index import index_version_for, publish, write_index

    projection, dictionary = build_projection(CANDIDATE_DB, snapshot_label="bad")
    vectors = {doc.doc_id: provider.embed([doc.text], kind="document")[0] for doc in projection.docs}
    version = index_version_for(projection, contract)
    write_index(
        target_dir=root / version,
        projection=projection,
        dictionary=dictionary,
        embedding=contract,
        vectors=vectors,
    )
    load_index(root, version=version).vector_for(projection.docs[0].doc_id)
    publish(root, version)


def test_vector_validation_rejects_bad_shapes():
    with pytest.raises(ValueError):
        validate_vector([1.0, 2.0], dimension=3)
    with pytest.raises(ValueError):
        validate_vector([float("nan")] * 3, dimension=3)
    with pytest.raises(ValueError):
        validate_vector([0.0, 0.0, 0.0], dimension=3)
    with pytest.raises(EmbeddingContractError):
        validate_and_normalize(
            [[0.1, 0.2, 0.3]], EmbeddingContract(model="m", revision="r", dimension=4)
        )


def test_query_instruction_is_applied_to_queries_only():
    contract = EmbeddingContract(
        model="m", revision="r", dimension=4, query_instruction="query: "
    )
    assert apply_instruction("糖醋排骨", contract, kind="query") == "query: 糖醋排骨"
    assert apply_instruction("糖醋排骨", contract, kind="document") == "糖醋排骨"


# ================================================================== retrieval


def test_exact_name_hit_needs_no_embedding_provider(db_session, tmp_path):
    build_index(tmp_path)
    failing = MockEmbeddingProvider(fails="EMBEDDING_NOT_CONFIGURED")
    result = service(db_session, tmp_path, provider=failing).search_dishes("糖醋排骨")
    assert result["status"] == "ok"
    assert result["hits"][0]["name"] == "糖醋排骨"
    assert result["hits"][0]["match_kind"] == "exact"
    assert failing.calls == [], "an exact name must not reach the embedding provider"


def test_registered_alias_hits_without_network(db_session, tmp_path):
    build_index(tmp_path)
    provider = MockEmbeddingProvider(fails="EMBEDDING_NOT_CONFIGURED")
    result = service(db_session, tmp_path, provider=provider).search_dishes("西红柿炒鸡蛋")
    assert result["status"] == "ok"
    assert result["hits"], result
    assert provider.calls == []


def test_lexical_route_finds_dishes_by_ingredient(db_session, tmp_path):
    build_index(tmp_path)
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes(
        "鸡蛋 豆腐"
    )
    assert result["hits"], result
    assert all(hit["match_kind"] in ("lexical", "fused", "semantic") for hit in result["hits"])
    assert all(len(item) <= 120 for hit in result["hits"] for item in hit["evidence"])


def test_fuzzy_match_does_not_short_circuit_the_hybrid_route(db_session, tmp_path):
    build_index(tmp_path, embed=True, provider=MockEmbeddingProvider())
    provider = MockEmbeddingProvider()
    result = service(db_session, tmp_path, provider=provider).search_dishes("番茄炒旦")
    # A near-miss name is a candidate, but retrieval still ran both routes.
    assert result["retrieval_mode"] == "hybrid"
    assert result["status"] == "ok"
    assert provider.calls, "a fuzzy name must not short-circuit the vector route"


def test_hard_exclusion_comes_from_the_real_validation_context(db_session, tmp_path):
    build_index(tmp_path)
    from app.agent.state import Requirements

    context = ValidationContext.from_requirements(
        Requirements(excluded_ingredients=["egg"]),
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes(
        "番茄炒蛋", context=context
    )
    # The exact name matches, but it conflicts with a stated exclusion — reported
    # as a conflict, never swapped for a similar dish.
    assert result["status"] == "ok"
    assert result["hits"] == []
    assert result["conflict"]["code"] == "CONSTRAINT_CONFLICT"
    assert result["conflict"]["conflicting_ingredients"] == ["egg"]
    assert "egg" in result["filters_applied"]["excluded_ingredient_ids"]


def test_negation_is_a_filter_and_never_a_vector(db_session, tmp_path):
    build_index(tmp_path, embed=True, provider=MockEmbeddingProvider())
    from app.agent.state import Requirements

    context = ValidationContext.from_requirements(
        Requirements(excluded_ingredients=["花生"]),
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )
    provider = MockEmbeddingProvider()
    result = service(db_session, tmp_path, provider=provider).search_products(
        "花生", context=context
    )
    # Whatever was embedded, no hit may carry the excluded ingredient.
    for hit in result["hits"]:
        payload = hit
        assert "peanut" not in json.dumps(payload, ensure_ascii=False)
    assert "peanut" in result["filters_applied"]["excluded_ingredient_ids"]


def test_unknown_constraints_are_reported_not_claimed(db_session, tmp_path):
    build_index(tmp_path)
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes(
        "清淡不辣的快手菜"
    )
    if result["hits"]:
        unknown = result["hits"][0]["unknown_constraints"]
        assert "taste" in unknown and "cook_minutes" in unknown


def test_missing_vectors_degrade_to_lexical_with_a_real_reason(db_session, tmp_path):
    build_index(tmp_path)  # lexical only: no embedding contract at all
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes("豆腐")
    assert result["status"] == "degraded"
    assert result["retrieval_mode"] == MODE_LEXICAL
    assert result["fallback_reason"] == "vector_index_missing"
    assert result["hits"], "the lexical route is still healthy and must still answer"


def test_degraded_with_no_hits_stays_degraded_and_empty(db_session, tmp_path):
    build_index(tmp_path)
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes(
        "zzzz-not-a-dish"
    )
    assert result["status"] == "degraded"
    assert result["hits"] == []
    assert result["empty"] is True


def test_active_lexical_mode_is_ok_not_a_failure(db_session, tmp_path):
    build_index(tmp_path)
    result = service(db_session, tmp_path, mode=MODE_LEXICAL).search_dishes("豆腐")
    assert result["status"] == "ok"
    assert result["retrieval_mode"] == MODE_LEXICAL
    assert result["fallback_reason"] is None


def test_incompatible_index_is_stale_and_never_answered_from(db_session, tmp_path):
    result = build_index(tmp_path)
    manifest_path = tmp_path / result["version"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lexical_tokenizer_version"] = "zh-dict-v0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(IndexUnavailable) as excinfo:
        load_index(tmp_path)
    assert excinfo.value.code == "INDEX_STALE"
    outcome = service(db_session, tmp_path).search_dishes("豆腐")
    assert outcome["status"] == "unavailable"
    assert outcome["hits"] == []


def test_fusion_uses_both_routes_and_reports_the_mode(db_session, tmp_path):
    provider = MockEmbeddingProvider()
    build_index(tmp_path, embed=True, provider=provider)
    result = service(db_session, tmp_path, provider=MockEmbeddingProvider()).search_dishes("豆腐")
    assert result["retrieval_mode"] == "hybrid"
    assert result["status"] == "ok"
    assert result["hits"]


def test_retrieval_never_writes_business_tables(db_session, tmp_path):
    build_index(tmp_path)
    tables = [
        "cart_items",
        "carts",
        "guide_tasks",
        "plan_snapshots",
        "catalog_products",
        "purchase_templates",
        "offers",
    ]
    def counts() -> dict[str, int]:
        return {
            table: db_session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in tables
        }

    before = counts()
    svc = service(db_session, tmp_path, provider=MockEmbeddingProvider(), verify_live=True)
    for query in ("糖醋排骨", "豆腐", "橄榄油", "不存在的菜"):
        svc.search_dishes(query)
        svc.search_products(query)
    assert counts() == before


# ============================================================== read tool wiring


def test_lookup_transports_retrieval_facts(db_session, tmp_path, monkeypatch):
    from app.agent.tools.read import ReadTools

    build_index(tmp_path, embed=True, provider=MockEmbeddingProvider())
    monkeypatch.setenv("RETRIEVAL_INDEX_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    tools = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default")
    tools._retrieval_service = service(
        db_session, tmp_path, provider=MockEmbeddingProvider()
    )
    candidates = CandidateSet()
    from app.agent.protocol import Lookup

    result = tools._lookup(Lookup(kind="dish", query="糖醋排骨"), candidates)
    assert result["status"] == "completed"
    assert result["retrieval_status"] == "ok"
    assert result["index_version"]
    assert result["matches"]
    match = result["matches"][0]
    for key in ("ref", "name", "target_id", "match_kind", "evidence",
                "review_status", "stock_verified", "unknown_constraints"):
        assert key in match
    assert match["ref"] in candidates.refs
    get_settings.cache_clear()


def test_recommend_aggregates_partial_sources(db_session, tmp_path, monkeypatch):
    from app.agent.tools.read import ReadTools

    build_index(tmp_path)  # no vectors -> the vector route degrades
    tools = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default")
    tools._retrieval_service = service(db_session, tmp_path, provider=MockEmbeddingProvider())
    facts = tools._collect_query("recommend", "火锅")
    assert facts["retrieval_status"] == "degraded"
    assert set(facts["partial_sources"]) == {"dishes", "products"}
    assert facts["partial_sources"]["dishes"]["status"] == "degraded"
    assert facts["fallback_reason"]


def test_recommend_without_topic_reports_incomplete_when_time_runs_out(db_session):
    from app.agent.tools.read import ReadTools

    tools = ReadTools(
        db_session,
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
        deadline_expired=lambda: True,
    )
    facts = tools._collect_query("recommend", None)
    assert facts["exploration"] is True
    assert facts["incomplete"] is True
    assert facts["retrieval_status"] == "degraded"
    assert facts["buildable_dishes"] == []


def test_suggest_buildable_dishes_can_scan_every_recipe(db_session):
    from app.services.template_plan_service import TemplatePlanService

    planner = TemplatePlanService(db_session, "store-demo-01", "zone-default")
    scanned: list[str] = []
    original = planner.build_plan

    def counting(dish, people, *args, **kwargs):
        scanned.append(dish.get("dish_id"))
        return original(dish, people, *args, **kwargs)

    planner.build_plan = counting  # type: ignore[assignment]
    planner.suggest_buildable_dishes(limit=30, scan=None)
    assert len(scanned) > 20, "a full scan must look past the first 20 fixture rows"
    assert planner.last_suggest_scan_exhausted is False


def test_allocate_rejects_an_unknown_candidate_kind():
    candidates = CandidateSet()
    with pytest.raises(SemanticProtocolError) as excinfo:
        candidates.allocate("spaceship", "x1", "不存在的类型")
    assert excinfo.value.code == "UNKNOWN_CANDIDATE_KIND"
    assert candidates.refs == {}


# ====================================================== index integrity & safety


def test_published_version_is_immutable(tmp_path):
    from app.services.retrieval_index import write_index

    result = build_index(tmp_path)
    projection, dictionary = build_projection(CANDIDATE_DB, snapshot_label="again")
    with pytest.raises(IndexUnavailable) as excinfo:
        write_index(
            target_dir=tmp_path / result["version"],
            projection=projection,
            dictionary=dictionary,
            embedding=None,
            vectors=None,
        )
    assert excinfo.value.code == "INDEX_EXISTS"
    # The live pointer and the version directory are both untouched.
    assert read_pointer(tmp_path) == result["version"]
    load_index(tmp_path).close()


def test_staging_commit_never_overwrites_and_reports_failure(tmp_path):
    from app.services.retrieval_index import stage_and_commit

    good = build_index(tmp_path)
    called = {"build": 0}

    def _build(staging):
        called["build"] += 1
        raise RuntimeError("build blew up half way")

    with pytest.raises(RuntimeError):
        stage_and_commit(
            index_root=tmp_path, version="idx-should-not-exist", build=_build, verify=lambda _: {}
        )
    assert called["build"] == 1
    assert read_pointer(tmp_path) == good["version"]
    assert not (tmp_path / "idx-should-not-exist").exists()
    # No staging leftovers either.
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".staging-")]


def test_snapshot_label_does_not_change_the_projection_identity(tmp_path):
    first, _ = build_projection(CANDIDATE_DB, snapshot_label="run-a")
    second, _ = build_projection(CANDIDATE_DB, snapshot_label="run-b")
    # A label is an audit note. If it changed the hash, the same corpus built
    # twice would look like two corpora.
    assert first.snapshot_hash == second.snapshot_hash


def test_swapped_dictionary_is_detected_by_content_hash(tmp_path):
    result = build_index(tmp_path)
    version_dir = tmp_path / result["version"]
    with sqlite3.connect(version_dir / "index.sqlite3") as conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'dictionary'",
                     (json.dumps({"version": "zh-dict-v1", "terms": [], "by_length": {},
                                  "single_chars": [], "single_char_expansions": {}}),))
    with pytest.raises(IndexUnavailable) as excinfo:
        load_index(tmp_path)
    assert excinfo.value.code == "INDEX_STALE"
    assert "dictionary" in excinfo.value.message


def test_exact_match_that_became_stale_is_never_substituted(db_session, tmp_path):
    """A named dish the live store no longer matches is reported, not replaced.

    The substitution is the failure mode this guards: the shopper named one dish
    and a similarly named one is returned instead, with no sign that a swap
    happened.
    """
    provider = MockEmbeddingProvider()
    build_index(tmp_path, embed=True, provider=provider)
    # verify_live=True is what makes the liveness path run at all.
    svc = service(db_session, tmp_path, provider=provider, verify_live=True)
    stale_doc = svc._candidate_pool(svc._load(), kind="dish")[0]
    svc._live_document_is_stale = lambda doc, kind: doc["doc_id"] == stale_doc["doc_id"]
    result = svc.search_dishes(stale_doc["name"])
    assert result["hits"] == []
    assert result["dropped_exact_match"]["target_id"] == stale_doc["target_id"]
    assert result["dropped_exact_match"]["code"] == "STALE_EXACT_MATCH"


def test_single_character_query_expands_only_through_the_frozen_dictionary(tmp_path, db_session):
    build_index(tmp_path)
    svc = service(db_session, tmp_path, mode="lexical")
    for char in ("蛋", "鱼"):
        result = svc.search_dishes(char)
        assert result["hits"], f"{char} should be a real query"
    # A character the dictionary has no term for cannot match anything.
    result = svc.search_dishes("龘")
    assert result["hits"] == []


def test_deployed_index_that_describes_another_corpus_is_unavailable(tmp_path, db_session):
    build_index(tmp_path)
    svc = service(db_session, tmp_path)
    svc._corpus_checked = False  # the live database is not this index's corpus
    from app.agent.protocol import Lookup
    from app.agent.tools.read import ReadTools

    reads = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default",
                      retrieval=svc)
    result = reads._lookup(Lookup(kind="dish", query="番茄炒蛋"), CandidateSet())
    assert result["retrieval_status"] == "unavailable"
    assert result["status"] == "failed"
    assert result["matches"] == []


# ============================================== read-only query constraints


def test_lookup_constraints_add_an_exclusion_on_a_first_turn(db_session, tmp_path):
    from app.agent.protocol import Lookup, parse_proposal
    from app.agent.state import Requirements

    build_index(tmp_path)
    proposal = parse_proposal({
        "lookups": [{"kind": "dish", "query": "蛋炒饭",
                     "constraints": {"excluded_ingredients": ["egg"]}}]
    })
    assert proposal.lookups[0].excluded_ingredients == ["egg"]
    from app.agent.tools.read import ReadTools

    reads = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default",
                      requirements=Requirements(), retrieval=service(db_session, tmp_path))
    facts = reads._lookup(proposal.lookups[0], CandidateSet())
    assert "egg" in facts["filters_applied"]["excluded_ingredient_ids"]
    assert facts["matches"] == [] or facts.get("conflict")


def test_lookup_constraints_cannot_silently_drop_a_saved_exclusion(db_session, tmp_path):
    from app.agent.protocol import Lookup
    from app.agent.state import Requirements
    from app.agent.tools.read import ReadTools

    build_index(tmp_path)
    reads = ReadTools(
        db_session, store_id="store-demo-01", delivery_zone_id="zone-default",
        requirements=Requirements(excluded_ingredients=["peanut"]),
        retrieval=service(db_session, tmp_path),
    )
    # The read states a *different* exclusion; the saved one must survive.
    facts = reads._lookup(
        Lookup(kind="dish", query="蛋炒饭", excluded_ingredients=["egg"]), CandidateSet()
    )
    applied = set(facts["filters_applied"]["excluded_ingredient_ids"])
    assert {"peanut", "egg"} <= applied


def test_lookup_constraints_are_rejected_when_malformed():
    from app.agent.protocol import parse_proposal

    with pytest.raises(SemanticProtocolError):
        parse_proposal({"lookups": [{"kind": "dish", "query": "x", "constraints": {"nope": 1}}]})


def test_recipe_candidates_are_allocated_refs(db_session, tmp_path):
    """A recipe answer's candidates must be referenceable, not just readable."""
    from app.agent.protocol import Query
    from app.agent.tools.read import ReadTools

    build_index(tmp_path)
    reads = ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default",
                      retrieval=service(db_session, tmp_path))
    candidates = CandidateSet()
    facts = reads._query(Query(kind="recipe", query="番茄炒蛋"), candidates)
    rows = [row for row in facts.get("candidates") or [] if row.get("dish_id")]
    assert rows, facts
    for row in rows:
        assert row.get("ref") in candidates.refs
        assert candidates.refs[row["ref"]].kind == "dish"

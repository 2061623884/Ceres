"""Independent acceptance probes. Never mutate the S1 snapshot or live database."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def rag_review(tmp_path):
    from app.services.retrieval_projection import build_projection
    from app.services.retrieval_index import write_index, publish
    from app.services.retrieval_service import RetrievalService

    root = Path(__file__).resolve().parents[2]
    source = root / "verification/data-completion/candidate_runtime.sqlite3"
    database = tmp_path / "business.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(database) as dest:
            src.backup(dest)
    projection, dictionary = build_projection(database)
    index_root = tmp_path / "index"
    write_index(target_dir=index_root / "v1", projection=projection,
                dictionary=dictionary, embedding=None, vectors=None)
    publish(index_root, "v1")
    engine = create_engine("sqlite:///" + database.as_posix())
    with Session(engine) as session:
        service = RetrievalService(session, store_id="store-demo-01",
                                   delivery_zone_id="zone-default",
                                   index_root=index_root, mode="lexical")
        yield service, database, index_root
        if getattr(service, "_index", None):
            service._index.close()
    engine.dispose()


def test_review_exact_id_is_named_match(rag_review):
    service, _, _ = rag_review
    result = service.search_dishes("dish-fanqie-chao-dan")
    assert result["status"] == "ok"
    assert result["hits"][0]["target_id"] == "dish-fanqie-chao-dan"
    assert result["hits"][0]["match_kind"] == "exact"


@pytest.mark.parametrize("query", ["demo:cola-330ml", "可乐 330毫升"])
def test_review_zero_stock_never_offered_as_product(rag_review, query):
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE offers SET available_qty=0 WHERE sku_id='demo:cola-330ml'")
    result = service.search_products(query)
    assert not any(h["target_id"] == "demo:cola-330ml" for h in result["hits"])


def test_review_deleted_exact_dish_is_not_resurrected_from_fixture(rag_review):
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM purchase_templates WHERE template_id='dish-fanqie-chao-dan'")
    result = service.search_dishes("番茄炒蛋")
    assert not any(h["target_id"] == "dish-fanqie-chao-dan" for h in result["hits"])


def test_review_changed_static_dish_cannot_keep_old_evidence(rag_review):
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE purchase_templates SET scenario='新菜名' WHERE template_id='dish-fanqie-chao-dan'")
    result = service.search_dishes("番茄炒蛋")
    assert not any(h["target_id"] == "dish-fanqie-chao-dan" for h in result["hits"])


def test_review_dish_recall_does_not_claim_strict_fulfillment(rag_review):
    service, _, _ = rag_review
    result = service.search_dishes("鸡蛋豆腐有什么菜")
    assert result["hits"]
    assert all(h["stock_verified"] is False for h in result["hits"])


def test_review_runtime_uses_frozen_ingredient_dictionary(rag_review, monkeypatch):
    service, _, _ = rag_review
    def forbidden():
        raise AssertionError("request path reloaded mutable ingredient fixture")
    monkeypatch.setattr("app.services.ingredient_catalog.load_ingredient_catalog", forbidden)
    # Also replace any names imported before monkeypatching the original module.
    import app.services.retrieval_projection as projection
    import app.services.retrieval_service as retrieval
    if hasattr(projection, "load_ingredient_catalog"):
        monkeypatch.setattr(projection, "load_ingredient_catalog", forbidden)
    if hasattr(retrieval, "load_ingredient_catalog"):
        monkeypatch.setattr(retrieval, "load_ingredient_catalog", forbidden)
    result = service.search_dishes("鸡蛋")
    assert result["status"] in ("ok", "empty")


def test_review_manifest_tamper_rejected(rag_review):
    service, _, index_root = rag_review
    path = index_root / "v1/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["counts"]["docs"] += 1
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = service.search_dishes("鸡蛋")
    assert result["status"] == "unavailable"


def test_review_broken_lexical_index_is_not_empty(rag_review):
    service, _, index_root = rag_review
    with sqlite3.connect(index_root / "v1/index.sqlite3") as conn:
        conn.execute("DROP TABLE docs_fts")
    result = service.search_dishes("鸡蛋")
    assert result["status"] == "unavailable"


def test_review_exact_exclusion_does_not_substitute(rag_review):
    from app.agent.state import Requirements
    from app.services.validation_context import ValidationContext
    service, _, _ = rag_review
    context = ValidationContext.from_requirements(
        Requirements(excluded_ingredients=["egg"]),
        store_id="store-demo-01", delivery_zone_id="zone-default")
    result = service.search_dishes("番茄炒蛋", context=context)
    assert result["hits"] == []
    assert (result.get("conflict") or {}).get("code") == "CONSTRAINT_CONFLICT" or result.get("code") == "CONSTRAINT_CONFLICT"


def test_review_http_query_instruction_once_and_normalization(rag_review):
    import httpx
    from app.llm.embedding import EmbeddingContract, HttpEmbeddingProvider
    from app.services.retrieval_projection import build_projection
    from app.services.retrieval_index import write_index, publish
    from app.services.retrieval_service import clear_query_cache

    service, database, index_root = rag_review
    contract = EmbeddingContract(model="review-model", revision="review-pinned-v1",
                                 dimension=2, query_instruction="Instruction\nQuery: ")
    received = []
    def respond(request):
        body = json.loads(request.content)
        received.extend(body["input"])
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]})
    provider = HttpEmbeddingProvider(base_url="https://embedding.invalid/v1", api_key="",
                                     contract=contract, transport=httpx.MockTransport(respond))
    projection, dictionary = build_projection(database)
    write_index(target_dir=index_root / "v2", projection=projection, dictionary=dictionary,
                embedding=contract.as_dict(), vectors={d.doc_id: [0.6, 0.8] for d in projection.docs})
    publish(index_root, "v2")
    clear_query_cache()
    service.mode = "hybrid"
    service.embedding_provider = provider
    result = service.search_dishes("鸡蛋")
    assert received == ["Instruction\nQuery: 鸡蛋"]
    assert result["status"] == "ok", result
    assert result["retrieval_mode"] == "hybrid"


def test_review_http_embedding_response_index_order():
    import httpx
    from app.llm.embedding import EmbeddingContract, HttpEmbeddingProvider
    body = {"data": [{"index": 1, "embedding": [0.0, 1.0]},
                     {"index": 0, "embedding": [1.0, 0.0]}]}
    provider = HttpEmbeddingProvider(base_url="https://embedding.invalid/v1", api_key="",
        contract=EmbeddingContract(model="test", revision="test", dimension=2),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    assert provider.embed(["first", "second"], kind="document") == [[1.0, 0.0], [0.0, 1.0]]


def test_review_request_does_not_autoflush_business_writes(rag_review):
    from sqlalchemy import event
    from app.models.catalog import CatalogProduct
    service, _, _ = rag_review
    row = service.db.get(CatalogProduct, "demo:cola-330ml")
    row.brand = "pending caller-owned change"
    writes = []
    def inspect_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            writes.append(statement)
    event.listen(service.db.get_bind(), "before_cursor_execute", inspect_statement)
    try:
        service.search_products("可乐")
        assert writes == [], "read-only search flushed caller-owned mutations"
    finally:
        event.remove(service.db.get_bind(), "before_cursor_execute", inspect_statement)
        service.db.rollback()


def test_review_changed_ingredient_evidence_is_stale(rag_review):
    from app.agent.state import Requirements
    from app.services.validation_context import ValidationContext
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE purchase_templates SET required_items=? WHERE template_id='dish-fanqie-chao-dan'",
                     (json.dumps([{"ingredient_id": "peanut", "quantity_g": 100}]),))
    context = ValidationContext.from_requirements(Requirements(excluded_ingredients=["peanut"]),
        store_id="store-demo-01", delivery_zone_id="zone-default")
    result = service.search_dishes("番茄炒蛋", context=context)
    assert result["hits"] == [], "same name does not imply unchanged ingredients"


def test_review_changed_product_mapping_is_stale(rag_review):
    from app.agent.state import Requirements
    from app.services.validation_context import ValidationContext
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE catalog_products SET ingredient_ids=? WHERE sku_id='demo:cola-330ml'",
                     (json.dumps(["peanut"]),))
    context = ValidationContext.from_requirements(Requirements(excluded_ingredients=["peanut"]),
        store_id="store-demo-01", delivery_zone_id="zone-default")
    result = service.search_products("demo:cola-330ml", context=context)
    assert result["hits"] == [], "live product mapping must override stale index evidence"


def test_review_unbuildable_dish_remains_retrievable(rag_review):
    service, database, _ = rag_review
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE offers SET available_qty=0, sellable=0")
    result = service.search_dishes("番茄炒蛋")
    assert result["hits"] and result["hits"][0]["target_id"] == "dish-fanqie-chao-dan"
    assert result["hits"][0]["stock_verified"] is False


def test_review_product_small_pack_hard_constraint(rag_review):
    from app.agent.state import Requirements
    from app.services.validation_context import ValidationContext
    service, _, _ = rag_review
    context = ValidationContext.from_requirements(Requirements(specification={"size": "small"}),
        store_id="store-demo-01", delivery_zone_id="zone-default")
    result = service.search_products("面粉", context=context)
    with sqlite3.connect(rag_review[1]) as conn:
        for hit in result["hits"]:
            size, unit = conn.execute("SELECT spec_quantity,spec_unit FROM catalog_products WHERE sku_id=?",
                                      (hit["target_id"],)).fetchone()
            assert size and unit in {"g", "kg", "ml", "l"}
            assert size * (1000 if unit in {"kg", "l"} else 1) <= 500


def test_review_missing_explicit_index_is_unavailable_not_legacy(rag_review, tmp_path):
    from app.agent.tools.read import ReadTools
    from app.agent.protocol import CandidateSet, Lookup
    from app.services.retrieval_service import RetrievalService
    service, _, _ = rag_review
    missing = RetrievalService(service.db, store_id="store-demo-01", delivery_zone_id="zone-default",
                                index_root=tmp_path / "missing-index", mode="lexical")
    reads = ReadTools(service.db, store_id="store-demo-01", delivery_zone_id="zone-default", retrieval=missing)
    result = reads._lookup(Lookup(kind="dish", query="番茄炒蛋"), CandidateSet())
    assert result["retrieval_status"] == "unavailable"
    assert result["matches"] == []


@pytest.mark.parametrize("damage", ["missing", "nan", "dimension"])
def test_review_bad_vector_component_degrades_independently(rag_review, damage):
    from app.llm.embedding import EmbeddingContract
    from app.services.retrieval_index import write_index, publish, pack_vector
    from app.services.retrieval_projection import build_projection
    service, database, index_root = rag_review
    contract = EmbeddingContract(model="review-vectors", revision="fixed", dimension=2)
    class Provider:
        def embed(self, texts, *, kind):
            return [[1.0, 0.0] for _ in texts]
    provider = Provider()
    provider.contract = contract
    projection, dictionary = build_projection(database)
    write_index(target_dir=index_root / "broken", projection=projection, dictionary=dictionary,
                embedding=contract.as_dict(), vectors={d.doc_id: [1.0, 0.0] for d in projection.docs})
    publish(index_root, "broken")
    with sqlite3.connect(index_root / "broken/index.sqlite3") as conn:
        if damage == "missing":
            conn.execute("DROP TABLE embeddings")
        elif damage == "nan":
            conn.execute("UPDATE embeddings SET vector=?", (pack_vector([float('nan'), 0.0]),))
        else:
            conn.execute("UPDATE embeddings SET dimension=3")
    service.mode = "hybrid"
    service.embedding_provider = provider
    result = service.search_dishes("鸡蛋")
    assert result["status"] == "degraded", result
    assert result["retrieval_mode"] == "lexical"
    assert result["hits"]


def test_review_delivery_is_checked_for_requested_zone(rag_review):
    service, _, _ = rag_review
    service.delivery_zone_id = "unreachable-zone"
    result = service.search_products("demo:cola-330ml")
    assert result["hits"] == []

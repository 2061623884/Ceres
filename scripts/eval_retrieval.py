#!/usr/bin/env python3
"""Offline retrieval evaluation against the annotated set.

Dev and holdout are reported separately and that separation is the point: the
acceptance thresholds are calibrated on dev only, so a holdout number that was
steered by tuning would be worthless.

Reporting rules this script follows, because the plan requires them:

* ``degraded`` results are counted as availability, never as hybrid quality.
* Answerable and unanswerable queries are separate denominators. An unanswerable
  query is reported as "wrong / total", not as a percentage of five.
* Latency is reported per stage as p50/p95, and a stage that was not measured is
  ``null`` rather than a made-up number.
* A mock embedding provider is labelled as mock in the report. Its numbers say
  nothing about real semantic quality.

    python scripts/eval_retrieval.py --mode lexical
    python scripts/eval_retrieval.py --mode hybrid --embed mock
    python scripts/eval_retrieval.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.services.retrieval_service import RetrievalService  # noqa: E402
from app.services.validation_context import ValidationContext  # noqa: E402

DEFAULT_SET = ROOT / "verification" / "rag" / "annotation-set.json"
DEFAULT_OUT_DIR = ROOT / "verification" / "rag"


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


class _SandboxEmbeddingProvider:
    """A mock provider, labelled as one everywhere it is reported.

    It hashes tokens into a fixed-width vector using **sha256, not Python's
    ``hash()``**: ``hash()`` of a string is salted per process, so an index built
    in one process and queried from another would use different vectors and
    silently produce nonsense. The tokenizer dictionary is supplied by the
    caller (the index's own frozen one) for the same reason — both sides must
    agree exactly.

    It carries no semantics, and its scores must never be presented as real
    embedding quality.
    """

    def __init__(self, dimension: int = 16):
        from app.llm.embedding import EmbeddingContract

        self.contract = EmbeddingContract(
            model="mock-hash-embedding", revision="stable-sha256-v1", dimension=dimension,
            query_instruction="query: ",
        )

    def embed(self, texts: list[str], *, kind: str) -> list[list[float]]:
        from app.services.retrieval_index import normalize_vector, validate_vector
        from app.services.retrieval_projection import tokenize

        dictionary = _mock_dictionary()
        vectors: list[list[float]] = []
        for text in texts:
            raw = [0.0] * self.contract.dimension
            for token in tokenize(text, dictionary):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                raw[int.from_bytes(digest[:4], "big") % self.contract.dimension] += 1.0
            if not any(raw):
                raw[0] = 1.0
            vectors.append(validate_vector(normalize_vector(raw), dimension=self.contract.dimension))
        return vectors


_MOCK_SNAPSHOT: Path | None = None
_MOCK_DICTIONARY: dict[str, Any] | None = None


def _mock_snapshot_path() -> Path:
    if _MOCK_SNAPSHOT is None:
        raise RuntimeError("mock snapshot path was not resolved")
    return _MOCK_SNAPSHOT


def _mock_dictionary() -> dict[str, Any]:
    """The index's frozen dictionary, so build and query tokenize identically."""
    global _MOCK_DICTIONARY
    if _MOCK_DICTIONARY is None:
        from app.services.retrieval_projection import build_dictionary, read_snapshot

        dishes, skus = read_snapshot(_mock_snapshot_path())
        _MOCK_DICTIONARY = build_dictionary(dish_rows=dishes, sku_rows=skus)
    return _MOCK_DICTIONARY


def build_mock_index(index_root: Path, snapshot: Path) -> str:
    """Build a mock-embedded index **inside ``index_root``** and return its version.

    Deliberately takes the root as an argument: the evaluation must never write
    into the deployed index directory, so an isolated root is mandatory rather
    than assumed.
    """
    from app.services.retrieval_index import (
        index_version_for,
        publish,
        stage_and_commit,
        write_index,
    )
    from app.services.retrieval_projection import build_projection

    global _MOCK_SNAPSHOT, _MOCK_DICTIONARY
    _MOCK_SNAPSHOT = snapshot
    _MOCK_DICTIONARY = None
    provider = _SandboxEmbeddingProvider()
    projection, dictionary = build_projection(snapshot, snapshot_label="eval-mock")
    vectors = {doc.doc_id: provider.embed([doc.text], kind="document")[0] for doc in projection.docs}
    contract = provider.contract.as_dict()
    version = index_version_for(projection, contract)

    def _build(staging: Path) -> None:
        write_index(
            target_dir=staging,
            projection=projection,
            dictionary=dictionary,
            embedding=contract,
            vectors=vectors,
            audit_only={
                "embedding_source": "MOCK sha256-token provider (not a real model)",
                "candidate_db_path": snapshot.as_posix(),
                "built_by": "eval_retrieval.py",
            },
        )

    stage_and_commit(
        index_root=index_root, version=version, build=_build, verify=lambda _staging: {"passed": True}
    )
    publish(index_root, version)
    return version


def _load_set(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def lint_annotations(payload: dict[str, Any]) -> list[str]:
    problems = []
    entries = payload.get("entries", [])
    if sum(e.get("split") == "dev" for e in entries) < 20 or sum(e.get("split") == "holdout" for e in entries) < 40:
        problems.append("need at least 20 dev and 40 holdout queries")
    seen, splits, query_splits = set(), {}, {}
    for entry in entries:
        if entry.get("id") in seen:
            problems.append("duplicate query id")
        seen.add(entry.get("id"))
        query = str(entry.get("query", "")).strip().casefold()
        if query in query_splits and query_splits[query] != entry.get("split"):
            problems.append(f"identical query crosses split: {query}")
        query_splits[query] = entry.get("split")
        if bool(entry.get("gold_ids")) != bool(entry.get("answerable")):
            problems.append(f"inconsistent answerability: {entry.get('id')}")
        for target in entry.get("gold_ids", []):
            key = (entry.get("entity_kind"), target)
            if key in splits and splits[key] != entry.get("split"):
                problems.append(f"entity crosses split: {target}")
            splits[key] = entry.get("split")
    return problems


def _filters_for(entry: dict[str, Any]) -> ValidationContext | None:
    constraints = entry.get("constraints") or {}
    if not constraints:
        return None
    from app.agent.state import Requirements

    return ValidationContext.from_requirements(
        Requirements(
            people=constraints.get("people"),
            budget_fen=constraints.get("budget_fen"),
            excluded_ingredients=list(constraints.get("excluded_ingredients") or []),
        ),
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )


def _doc_ingredients(index: Any, kind: str, target_id: str) -> set[str]:
    """The declared ingredient ids of a hit, read from the index itself.

    A hard-condition violation has to be decided on *structured ids*. Searching
    the rendered hit for the English string "peanut" proves nothing: the hit
    carries Chinese evidence, so that check could never fail and was measuring
    nothing at all.
    """
    doc_kind = "dish" if kind == "dish" else "sku"
    for doc in index.docs_by_target(doc_kind, target_id):
        payload = json.loads(doc["payload_json"] or "{}")
        ids = set(payload.get("all_ingredient_ids") or [])
        ids |= set(payload.get("declared_ingredient_ids") or [])
        ids |= set(payload.get("verified_mapping_relations") or [])
        ids |= {str(p) for p in payload.get("pantry_items") or []}
        return ids
    return set()


def _evaluate_entry(
    service: RetrievalService,
    entry: dict[str, Any],
    *,
    index: Any,
    id_universe: dict[str, set[str]],
) -> dict[str, Any]:
    context = _filters_for(entry)
    started = time.perf_counter()
    if entry["entity_kind"] == "sku":
        result = service.search_products(entry["query"], context=context, limit=5)
    else:
        result = service.search_dishes(entry["query"], context=context, limit=5)
    call_ms = (time.perf_counter() - started) * 1000.0
    hits = result.get("hits") or []
    ids = [str(hit["target_id"]) for hit in hits]
    gold = [str(g) for g in entry.get("gold_ids") or []]

    # Recall is over *gold ids*, not a single rank: a query with three correct
    # answers that returns one of them is a third of a recall, not a hit.
    found = [g for g in gold if g in ids]
    ranks = [ids.index(g) + 1 for g in gold if g in ids]
    reciprocal = 0.0
    for rank in ranks:
        if rank <= 5:
            reciprocal = max(reciprocal, 1.0 / rank)

    excluded = set()
    if context is not None and context.excluded_ingredients:
        from app.services.retrieval_service import RetrievalFilters

        excluded = set(
            RetrievalFilters.from_context(
                context, ingredient_aliases=index.ingredient_maps()["aliases"]
            ).excluded_ingredient_ids
        )
    violations = 0
    unknown: list[str] = list(result.get("unknown_constraints") or [])
    for hit in hits:
        if excluded and excluded & _doc_ingredients(index, entry["entity_kind"], str(hit["target_id"])):
            violations += 1
        for name in hit.get("unknown_constraints") or []:
            if name not in unknown:
                unknown.append(name)

    universe = id_universe.get("sku" if entry["entity_kind"] == "sku" else "dish", set())
    ids_valid = bool(ids) and all(i in universe for i in ids)
    return {
        "id": entry["id"],
        "split": entry["split"],
        "category": entry["category"],
        "status": result["status"],
        "retrieval_mode": result.get("retrieval_mode"),
        "ids": ids,
        "gold": gold,
        "recall": (len(found) / len(gold)) if gold else None,
        "reciprocal_rank": reciprocal,
        "answerable": bool(entry.get("answerable", True)),
        "returned_hits": bool(hits),
        "hard_violations": violations,
        "ids_all_in_live_catalog": ids_valid,
        "valid_id_count": sum(i in universe for i in ids),
        "call_ms": call_ms,
        "unknown_constraints": unknown,
        "expected_unknown": entry.get("expected_unknown") or [],
    }


def _summarize(rows: list[dict[str, Any]], *, denominator_note: str) -> dict[str, Any]:
    # Degraded retrieval is availability evidence, never hybrid quality success.
    quality_rows = [r for r in rows if r["status"] != "degraded"]
    answerable = [r for r in quality_rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    # Recall@5 is the mean of the per-query *gold-id* recall, so a query with
    # several correct answers cannot be scored as fully solved by returning one.
    # MRR@5 averages over every answerable query, counting a miss as 0.0 —
    # averaging only the hits would report a rank quality that ignores failure.
    recalls = [r["recall"] or 0.0 for r in answerable]
    rr = [r["reciprocal_rank"] for r in answerable]
    latencies = [r["call_ms"] for r in rows]
    answered = [r for r in answerable if r["returned_hits"]]
    # An unanswerable query is only *wrong* if the service actually offered
    # something. "empty" and "unavailable" are the correct outcomes here — and a
    # degraded run that returned nothing is also not a false positive.
    false_positives = [r for r in unanswerable if r["returned_hits"]]
    return {
        "queries": len(rows),
        "quality_queries_excluding_degraded": len(quality_rows),
        "denominator_note": denominator_note,
        "answerable_total": len(answerable),
        "answerable_with_hits": len(answered),
        "recall_at_5": (statistics.fmean(recalls) if recalls else None),
        "mrr_at_5": (statistics.fmean(rr) if rr else None),
        "no_answer_false_positive": len(false_positives),
        "no_answer_total": len(unanswerable),
        "no_answer_false_positive_ids": [r["id"] for r in false_positives],
        "hard_condition_violations": sum(r["hard_violations"] for r in rows),
        # "Candidate facts are 100% valid ids" is a claim about the ids that were
        # actually offered, so the denominator is the queries that returned any —
        # not every query, which would let empty answers inflate the rate.
        "queries_with_ids": sum(1 for r in rows if r["ids"]),
        "ids_all_in_live_catalog": sum(1 for r in rows if r["ids_all_in_live_catalog"]),
        "id_valid_rate": (
            sum(1 for r in rows if r["ids_all_in_live_catalog"])
            / sum(1 for r in rows if r["ids"])
            if any(r["ids"] for r in rows) else None
        ),
        "status_counts": {
            status: sum(1 for r in rows if r["status"] == status)
            for status in ("ok", "degraded", "empty", "unavailable")
        },
        # Availability is reported on its own line. It is never folded into the
        # quality numbers: a lexical fallback answering a query is not evidence
        # that hybrid retrieval works.
        "degraded_availability": sum(1 for r in rows if r["status"] == "degraded"),
        "degraded_with_hits": sum(
            1 for r in rows if r["status"] == "degraded" and r["returned_hits"]
        ),
        "latency_ms": {
            # What was actually measured: one whole search call, including any
            # embedding request and live verification it performed. Reporting it
            # as "retrieve" would attribute embedding time to the wrong stage.
            "search_call_p50": _percentile(latencies, 0.5),
            "search_call_p95": _percentile(latencies, 0.95),
            "retrieve_p50": None,
            "retrieve_p95": None,
            "embed_p50": None,
            "embed_p95": None,
            "live_verify_p50": None,
            "live_verify_p95": None,
            "turn_p50": None,
            "turn_p95": None,
        },
        "expected_unknown_reported": sum(
            1 for r in rows
            if r["expected_unknown"]
            and set(r["expected_unknown"]).issubset(set(r["unknown_constraints"]))
        ),
        "expected_unknown_total": sum(1 for r in rows if r["expected_unknown"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="eval_retrieval.py",
        description="Evaluate the retrieval service against the annotated set (offline, read-only).",
    )
    parser.add_argument("--annotation-set", default=str(DEFAULT_SET))
    parser.add_argument("--index-root", required=True,
                        help="index root to evaluate against; MUST be isolated from the deployed one")
    parser.add_argument("--candidate-db", default=None,
                        help="snapshot to read (default: the annotation set's snapshot)")
    parser.add_argument("--mode", choices=("lexical", "hybrid"), default="hybrid")
    parser.add_argument("--embed", choices=("none", "mock", "http"), default="none",
                        help="mock is clearly labelled in the report; it is not a real model")
    parser.add_argument("--build-mock-index", action="store_true",
                        help="build the mock-embedded index inside --index-root before evaluating")
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all",
                        help="dev is for tuning; holdout is reported, never tuned on")
    parser.add_argument("--live-verify", action="store_true",
                        help="also verify hits against the snapshot (read-only)")
    parser.add_argument("--out", default=None, help="write the JSON report to this path")
    args = parser.parse_args()

    payload = _load_set(Path(args.annotation_set))
    problems = lint_annotations(payload)
    if problems:
        raise SystemExit("invalid annotation set: " + "; ".join(problems))
    entries = payload["entries"]
    if args.split != "all":
        entries = [entry for entry in entries if entry["split"] == args.split]

    index_root = Path(args.index_root).resolve()
    deployed = (ROOT / "data" / "retrieval_index").resolve()
    if index_root == deployed:
        # The evaluation builds and publishes indexes. Doing that in the deployed
        # root would make the measurement itself a change to what the product
        # serves, which is not an evaluation.
        raise SystemExit(
            f"--index-root must be an isolated directory, not the deployed index root ({deployed}). "
            "Pass e.g. --index-root <tmp>/rag-eval."
        )
    candidate = Path(
        args.candidate_db or payload.get("snapshot", {}).get("candidate_db_path") or ""
    )
    if not candidate.is_file():
        raise SystemExit(f"snapshot not found: {candidate}")

    global _MOCK_SNAPSHOT
    _MOCK_SNAPSHOT = candidate
    provider = None
    embedding_label = "none"
    index_version = None
    if args.embed == "mock":
        provider = _SandboxEmbeddingProvider()
        embedding_label = "MOCK (not a real model; semantic numbers are not evidence)"
    elif args.embed == "http":
        from app.llm.embedding import HttpEmbeddingProvider
        provider = HttpEmbeddingProvider.from_env()
        embedding_label = "HTTP real embedding (explicitly requested)"
    if args.build_mock_index:
        if args.embed != "mock":
            raise SystemExit("--build-mock-index requires --embed mock")
        index_version = build_mock_index(index_root, candidate)
        print(f"[eval] built mock index {index_version} under {index_root}")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Read-only, and against the **snapshot**: the deployed runtime database is
    # never opened by an evaluation, even with --live-verify.
    url = f"sqlite:///file:{candidate.as_posix()}?mode=ro&uri=true"
    engine = create_engine(url)
    session = sessionmaker(bind=engine)()
    try:
        if args.mode == "lexical":
            provider = None
        service = RetrievalService(
            session,
            store_id="store-demo-01",
            delivery_zone_id="zone-default",
            index_root=args.index_root,
            mode=args.mode,
            embedding_provider=provider,
            verify_live=args.live_verify,
        )
        index = service._load()
        if index is None:
            raise SystemExit(f"no usable index under {index_root}; pass --build-mock-index or build one first")
        # The live id universe, used to decide whether a returned id is a real
        # current catalog id — not merely a non-empty string.
        from sqlalchemy import text
        id_universe = {
            "dish": set(session.execute(text("SELECT template_id FROM purchase_templates WHERE source='chinese-dishes-v1'")).scalars()),
            "sku": set(session.execute(text("SELECT sku_id FROM catalog_products WHERE review_status='approved'")).scalars()),
        }
        from app.services.retrieval_projection import build_projection
        current_projection, _ = build_projection(candidate)
        if index.snapshot_hash != current_projection.snapshot_hash:
            raise SystemExit("evaluation index and candidate static snapshot differ; rebuild first")
        expected_snapshot = payload.get("snapshot", {}).get("projection_snapshot_hash")
        if expected_snapshot and expected_snapshot != index.snapshot_hash:
            raise SystemExit("annotation set belongs to another snapshot; explicit relabelling required")
        rows = [
            _evaluate_entry(service, entry, index=index, id_universe=id_universe)
            for entry in entries
        ]
    finally:
        if 'service' in locals() and service._index:
            service._index.close()
        session.close()
        engine.dispose()

    by_split: dict[str, Any] = {}
    for split in ("dev", "holdout"):
        subset = [r for r in rows if r["split"] == split]
        if subset:
            by_split[split] = _summarize(
                subset,
                denominator_note=f"{split}: recall/MRR over answerable queries only",
            )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "annotation_set": str(args.annotation_set),
        "annotation_set_version": payload.get("version"),
        "snapshot": payload.get("snapshot"),
        "mode": args.mode,
        "split_filter": args.split,
        "index_root": str(index_root),
        "index_version": index_version or service._index.version if service._index else None,
        "index_manifest_id": (service._index.manifest.get("manifest_id") if service._index else None),
        "index_projection_snapshot_hash": (
            service._index.snapshot_hash if service._index else None
        ),
        "database": {"url": url, "read_only": True, "is_snapshot": True},
        "embedding_provider": embedding_label,
        "embedding_is_mock": args.embed == "mock",
        "live_verify": bool(args.live_verify),
        "caveat": (
            "Mock embedding scores describe plumbing only. They are not evidence that "
            "real semantic retrieval quality was met."
            if args.embed == "mock" else
            "Lexical-only or vector-less run: no semantic quality claim is made."
        ),
        "overall": _summarize(rows, denominator_note="all evaluated queries"),
        "by_split": by_split,
        "by_category": {
            category: _summarize([r for r in rows if r["category"] == category], denominator_note=category)
            for category in sorted({r["category"] for r in rows})
        },
        "rows": rows,
    }
    print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

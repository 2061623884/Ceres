"""Regression tests for the evaluation statistics themselves.

An evaluation that misreports is worse than no evaluation, because it is
believed. Each test here pins one way the numbers used to flatter the system:

* MRR averaged only over the queries that hit, so a miss simply vanished;
* "recall" was a hit-rate, so a query with three correct answers scored the same
  whether one or all three came back;
* a miss on an unanswerable query counted as a false positive even when the
  service correctly returned nothing, and a degraded run that returned nothing
  was counted too;
* the id check only asked whether a string was non-empty;
* the hard-condition check searched the rendered hit for an English ingredient
  id, which can never appear — so it could never fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_retrieval  # noqa: E402


def row(**overrides):
    base = {
        "id": "q1",
        "split": "dev",
        "category": "exact",
        "status": "ok",
        "retrieval_mode": "hybrid",
        "ids": [],
        "gold": [],
        "recall": None,
        "reciprocal_rank": 0.0,
        "answerable": True,
        "returned_hits": False,
        "hard_violations": 0,
        "ids_all_in_live_catalog": False,
        "call_ms": 1.0,
        "unknown_constraints": [],
        "expected_unknown": [],
    }
    base.update(overrides)
    return base


def test_mrr_counts_a_miss_as_zero():
    rows = [
        row(id="hit", reciprocal_rank=1.0),
        row(id="miss", reciprocal_rank=0.0),
    ]
    summary = eval_retrieval._summarize(rows, denominator_note="test")
    # The old implementation averaged only the hits and reported 1.0 here.
    assert summary["mrr_at_5"] == pytest.approx(0.5)


def test_recall_is_over_gold_ids_not_a_hit_flag():
    rows = [
        row(id="partial", recall=1 / 3),
        row(id="full", recall=1.0),
    ]
    summary = eval_retrieval._summarize(rows, denominator_note="test")
    assert summary["recall_at_5"] == pytest.approx(2 / 3)


def test_an_empty_answer_to_an_unanswerable_query_is_not_a_false_positive():
    rows = [
        row(id="ok-empty", answerable=False, status="empty", returned_hits=False),
        row(id="ok-unavailable", answerable=False, status="unavailable", returned_hits=False),
        # A degraded run that returned nothing is also not a wrong answer.
        row(id="degraded-empty", answerable=False, status="degraded", returned_hits=False),
        row(id="really-wrong", answerable=False, status="ok", returned_hits=True),
    ]
    summary = eval_retrieval._summarize(rows, denominator_note="test")
    assert summary["no_answer_false_positive"] == 1
    assert summary["no_answer_false_positive_ids"] == ["really-wrong"]
    assert summary["no_answer_total"] == 4


def test_degraded_availability_is_reported_separately_from_quality():
    rows = [
        row(id="a", status="degraded", returned_hits=True, reciprocal_rank=1.0, recall=1.0),
        row(id="b", status="ok", returned_hits=True, reciprocal_rank=0.5, recall=1.0),
    ]
    summary = eval_retrieval._summarize(rows, denominator_note="test")
    assert summary["degraded_availability"] == 1
    assert summary["degraded_with_hits"] == 1
    # Degraded lexical answers cannot inflate successful hybrid quality.
    assert summary["status_counts"]["degraded"] == 1
    assert summary["mrr_at_5"] == pytest.approx(0.5)
    assert summary["quality_queries_excluding_degraded"] == 1


def test_unmeasured_latency_stages_are_null_not_guessed():
    summary = eval_retrieval._summarize([row(call_ms=3.0)], denominator_note="test")
    latency = summary["latency_ms"]
    assert latency["search_call_p50"] == pytest.approx(3.0)
    for stage in ("embed_p50", "embed_p95", "live_verify_p50", "live_verify_p95",
                  "turn_p50", "turn_p95", "retrieve_p50", "retrieve_p95"):
        assert latency[stage] is None, f"{stage} was never measured and must be null"


def test_id_validity_is_checked_against_the_live_catalog():
    rows = [
        row(id="good", ids=["dish-a"], ids_all_in_live_catalog=True),
        row(id="ghost", ids=["dish-deleted"], ids_all_in_live_catalog=False),
        # A query that returned nothing contributes to no denominator here: the
        # claim is about the ids that were offered.
        row(id="empty", ids=[], ids_all_in_live_catalog=False),
    ]
    summary = eval_retrieval._summarize(rows, denominator_note="test")
    assert summary["queries_with_ids"] == 2
    assert summary["ids_all_in_live_catalog"] == 1
    assert summary["id_valid_rate"] == pytest.approx(0.5)


def test_hard_violations_are_decided_on_structured_ids():
    """A rendered hit carries Chinese evidence, so a string search for an
    English ingredient id can never match — the old check was vacuous."""
    from app.services.retrieval_projection import build_projection

    snapshot = ROOT / "verification" / "data-completion" / "candidate_runtime.sqlite3"
    if not snapshot.is_file():
        pytest.skip("S1 candidate snapshot is not present")
    projection, _dictionary = build_projection(snapshot, snapshot_label="eval-test")
    target = next(
        doc for doc in projection.of_kind("dish")
        if "egg" in (doc.payload.get("all_ingredient_ids") or [])
    )
    class _Index:
        ingredient_maps = staticmethod(lambda: {"names": {}, "aliases": {}})
        docs_by_target = staticmethod(
            lambda kind, tid: [
                {"payload_json": __import__("json").dumps(doc.payload)}
                for doc in projection.of_kind(kind) if doc.target_id == tid
            ]
        )
    assert "egg" in eval_retrieval._doc_ingredients(_Index(), "dish", target.target_id)
    assert eval_retrieval._doc_ingredients(_Index(), "dish", "no-such-dish") == set()

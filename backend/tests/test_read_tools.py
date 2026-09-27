"""The read-only port: what a retrieval may return, and what it must not.

Two properties matter here, and both are correctness rather than features:

* a search expression is really used — ``推荐番茄炒蛋`` must not answer with
  whatever happens to sort first, and an empty result must stay empty instead of
  falling back to the catalogue's first rows;
* a blank or punctuation-only string is not a search at all, so ``?`` can never
  match a product whose name happens to contain it.

The port runs against the real seeded store; only the model is scripted elsewhere.
"""

from __future__ import annotations

import pytest

from app.agent.protocol import CandidateSet, Query, SemanticProposal
from app.agent.tools.read import ReadTools, searchable


@pytest.fixture()
def reads(db_session):
    return ReadTools(db_session, store_id="store-demo-01", delivery_zone_id="zone-default")


def serve(reads, *, lookups=(), queries=(), limit=2):
    proposal = SemanticProposal(lookups=list(lookups), queries=list(queries))
    return reads.serve(proposal, CandidateSet(), lookup_limit=limit)


def find(reads, kind, query):
    (result,) = serve(reads, lookups=[__import__("app.agent.protocol", fromlist=["Lookup"]).Lookup(kind, query)])
    return result


# ------------------------------------------------------------------- searchable


@pytest.mark.parametrize("text", ["", "   ", "?", "？", "  ?  ", "!!!", "。。"])
def test_a_blank_or_symbol_only_query_is_not_a_search(text):
    assert searchable(text) is False


@pytest.mark.parametrize("text", ["鸡蛋", "番茄炒蛋", "milk", "可乐330"])
def test_a_real_query_is_searchable(text):
    assert searchable(text) is True


def test_a_punctuation_lookup_is_refused_without_searching(reads):
    from app.agent.protocol import Lookup

    (result,) = serve(reads, lookups=[Lookup("product", "?")])
    assert result["status"] == "failed"
    assert result["code"] == "EMPTY_QUERY"
    assert result["matches"] == []


def test_a_punctuation_recommend_topic_is_refused_without_searching(reads):
    (result,) = serve(reads, queries=[Query("recommend", "?")])
    assert result["status"] == "failed"
    assert result["code"] == "EMPTY_QUERY"
    assert result["buildable_dishes"] == []
    assert result["sellable_products"] == []


# --------------------------------------------------------- the query is really used


def test_a_named_product_query_returns_that_product(reads):
    from app.agent.protocol import Lookup

    (result,) = serve(reads, lookups=[Lookup("product", "可乐")])
    names = [row["name"] for row in result["matches"]]
    assert names, result
    assert all("可乐" in name for name in names), names


def test_a_named_dish_query_returns_that_dish(reads):
    from app.agent.protocol import Lookup

    (result,) = serve(reads, lookups=[Lookup("dish", "番茄炒蛋")])
    names = [row["name"] for row in result["matches"]]
    assert names, result
    assert any("番茄" in name for name in names), names


def test_an_unmatched_query_returns_empty_rather_than_the_catalogue(reads):
    from app.agent.protocol import Lookup

    (result,) = serve(reads, lookups=[Lookup("product", "键盘")])
    assert result["status"] == "completed"
    assert result["empty"] is True
    assert result["matches"] == []


def test_two_topics_do_not_return_the_same_rows(reads):
    """The defect this replaces: every recommendation looked identical."""
    cola = serve(reads, queries=[Query("recommend", "可乐")])[0]
    tomato = serve(reads, queries=[Query("recommend", "番茄炒蛋")])[0]
    cola_names = {row["name"] for row in cola["sellable_products"]}
    tomato_names = {row["name"] for row in tomato["sellable_products"]}
    assert cola_names and tomato_names
    assert cola_names != tomato_names
    assert all("可乐" in name for name in cola_names), cola_names
    # The egg row belongs to 番茄炒蛋 through its own usage tag, and must not
    # appear for an unrelated topic.
    assert cola_names.isdisjoint(tomato_names), (cola_names, tomato_names)


def test_an_unmatched_recommend_topic_is_empty_not_a_default_list(reads):
    result = serve(reads, queries=[Query("recommend", "键盘")])[0]
    assert result["status"] == "completed"
    assert result["empty"] is True
    assert result["buildable_dishes"] == []
    assert result["sellable_products"] == []


def test_the_open_recommendation_is_labelled_as_exploration(reads):
    """No topic: real buildable dishes, explicitly not a filtered answer."""
    result = serve(reads, queries=[Query("recommend")])[0]
    assert result["status"] == "completed"
    assert result["exploration"] is True
    assert result["buildable_dishes"]
    # Nothing is padded in from unrelated products.
    assert "sellable_products" not in result


def test_recommend_rows_are_referenceable(reads):
    candidates = CandidateSet()
    proposal = SemanticProposal(queries=[Query("recommend", "番茄炒蛋")])
    (result,) = reads.serve(proposal, candidates, lookup_limit=2)
    refs = [row["ref"] for row in result["buildable_dishes"]]
    assert refs
    assert all(candidates.resolve(ref) is not None for ref in refs)

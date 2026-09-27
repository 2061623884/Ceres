"""The read contract: one exclusion rule and one evidence vocabulary everywhere.

Three properties, all of them correctness rather than features:

* a constraint the shopper states — an exclusion, a budget — is expressible on
  every read kind (lookup, recommend, recipe) and is **unioned** with what is
  already saved, so a read can add an exclusion and can never lift one;
* an exclusion is a hard filter on the pre-index path too, not only when a
  retrieval index happens to be deployed;
* a read that could not run is reported as failed and a read that ran and found
  nothing as empty, and the evidence behind either — which route ran, what was
  filtered, a conflict, a dropped exact match — survives to the model.

Everything here runs against the real seeded store on the pre-index path; the
indexed route is exercised for its unavailable lifecycle only. This file is not
evidence that semantic retrieval quality is met.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.agent.protocol import (
    CandidateSet,
    Lookup,
    Query,
    SemanticProposal,
    SemanticProtocolError,
    parse_proposal,
    proposal_schema,
)
from app.agent.state import Requirements
from app.agent.tools.read import ReadTools
from app.services.catalog_service import CatalogService
from app.services.template_matcher import load_templates
from app.services.template_plan_service import TemplatePlanService

STORE = "store-demo-01"
ZONE = "zone-default"


@pytest.fixture()
def reads(db_session):
    return ReadTools(db_session, store_id=STORE, delivery_zone_id=ZONE)


def serve(reads, *, lookups=(), queries=()):
    proposal = SemanticProposal(lookups=list(lookups), queries=list(queries))
    return reads.serve(proposal, CandidateSet(), lookup_limit=4)


def names_of(rows):
    return [row.get("name") for row in rows]


# ------------------------------------------------------- the protocol: queries


def test_a_query_carries_the_same_read_only_constraints_a_lookup_does():
    proposal = parse_proposal(
        {
            "queries": [
                {
                    "kind": "recipe",
                    "query": "番茄炒蛋",
                    "constraints": {"excluded_ingredients": ["peanut"], "budget_yuan": 30},
                }
            ]
        }
    )
    query = proposal.queries[0]
    assert query.excluded_ingredients == ["peanut"]
    # Yuan in, fen out. The model never authors a minor-unit amount.
    assert query.budget_fen == 3000


def test_a_query_cannot_hand_over_a_fen_amount():
    with pytest.raises(SemanticProtocolError) as excinfo:
        parse_proposal(
            {"queries": [{"kind": "recommend", "constraints": {"budget_fen": 3000}}]}
        )
    assert excinfo.value.code == "FORBIDDEN_FIELD"


def test_a_session_query_takes_no_constraints_to_apply_them_to():
    with pytest.raises(SemanticProtocolError) as excinfo:
        parse_proposal(
            {
                "queries": [
                    {"kind": "cart", "constraints": {"excluded_ingredients": ["peanut"]}}
                ]
            }
        )
    assert excinfo.value.code == "UNSUPPORTED_OPERATION"


def test_the_schema_advertises_constraints_on_the_retrieving_queries():
    forms = {
        form["properties"]["kind"].get("const") or "session": form["properties"]
        for form in proposal_schema()["properties"]["queries"]["items"]["oneOf"]
    }
    assert "constraints" in forms["recommend"]
    assert "constraints" in forms["recipe"]
    assert "constraints" not in forms["session"]
    # Same field, same yuan-only rule as a lookup's constraints.
    assert "budget_yuan" in forms["recommend"]["constraints"]["properties"]
    assert "budget_fen" not in str(forms["recommend"]["constraints"])


# ------------------------------------------- three entries, one hard exclusion


def test_a_first_turn_exclusion_filters_a_dish_lookup(reads):
    (unfiltered,) = serve(reads, lookups=[Lookup("dish", "番茄炒蛋")])
    assert [name for name in names_of(unfiltered["matches"]) if "番茄" in name]

    (filtered,) = serve(
        reads, lookups=[Lookup("dish", "番茄炒蛋", excluded_ingredients=["egg"])]
    )
    assert filtered["matches"] == []
    # The named dish collides with a stated exclusion: it is reported, never
    # quietly swapped for a similar dish.
    assert filtered["conflict"]["code"] == "CONSTRAINT_CONFLICT"
    assert filtered["filters_applied"]["excluded_ingredient_ids"] == ["egg"]


def test_a_first_turn_exclusion_filters_a_recipe_query(reads):
    (filtered,) = serve(
        reads, queries=[Query("recipe", "番茄炒蛋", excluded_ingredients=["egg"])]
    )
    assert filtered["candidates"] == []
    assert filtered["conflict"]["code"] == "CONSTRAINT_CONFLICT"
    assert filtered["filters_applied"]["excluded_ingredient_ids"] == ["egg"]


def test_a_first_turn_exclusion_filters_a_recommend_query(reads):
    (unfiltered,) = serve(reads, queries=[Query("recommend", "番茄炒蛋")])
    assert any("番茄" in (name or "") for name in names_of(unfiltered["buildable_dishes"]))

    (filtered,) = serve(
        reads, queries=[Query("recommend", "番茄炒蛋", excluded_ingredients=["egg"])]
    )
    assert not any("番茄" in (name or "") for name in names_of(filtered["buildable_dishes"]))
    assert filtered["filters_applied"]["excluded_ingredient_ids"] == ["egg"]


def test_an_excluded_ingredient_filters_the_pre_index_product_path(reads):
    rows = reads.find_products("可乐")
    assert rows, "the demo cola must be findable, or this proves nothing"
    assert reads.find_products("可乐", excluded=["cola"]) == []


def test_a_stated_exclusion_is_unioned_with_the_saved_one(db_session):
    """A read adds an exclusion; it can never lift one that is already saved."""
    saved = ReadTools(
        db_session,
        store_id=STORE,
        delivery_zone_id=ZONE,
        requirements=Requirements(excluded_ingredients=["egg"]),
    )
    (result,) = serve(
        saved, queries=[Query("recipe", "番茄炒蛋", excluded_ingredients=["tomato"])]
    )
    assert result["candidates"] == []
    assert result["filters_applied"]["excluded_ingredient_ids"] == ["egg", "tomato"]


def test_a_read_that_states_nothing_still_honours_the_saved_exclusion(db_session):
    saved = ReadTools(
        db_session,
        store_id=STORE,
        delivery_zone_id=ZONE,
        requirements=Requirements(excluded_ingredients=["egg"]),
    )
    (result,) = serve(saved, queries=[Query("recommend", "番茄炒蛋")])
    assert not any("番茄" in (name or "") for name in names_of(result["buildable_dishes"]))
    assert result["filters_applied"]["excluded_ingredient_ids"] == ["egg"]


def test_the_open_recommendation_honours_a_stated_exclusion(reads):
    (filtered,) = serve(reads, queries=[Query("recommend", excluded_ingredients=["egg"])])
    assert filtered["buildable_dishes"]
    assert "番茄炒蛋" not in names_of(filtered["buildable_dishes"])
    assert filtered["filters_applied"]["excluded_ingredient_ids"] == ["egg"]


# ------------------------------------------------------- failed vs. empty


def test_an_unavailable_index_fails_every_read_kind(db_session, tmp_path):
    from app.services.retrieval_service import RetrievalService

    missing = RetrievalService(
        db_session,
        store_id=STORE,
        delivery_zone_id=ZONE,
        index_root=tmp_path / "absent",
        mode="lexical",
    )
    reads = ReadTools(
        db_session, store_id=STORE, delivery_zone_id=ZONE, retrieval=missing
    )
    results = serve(
        reads,
        lookups=[Lookup("dish", "番茄炒蛋")],
        queries=[Query("recipe", "番茄炒蛋"), Query("recommend", "番茄炒蛋")],
    )
    assert len(results) == 3
    for result in results:
        assert result["status"] == "failed", result
        assert result["retrieval_status"] == "unavailable"
        assert result["code"]
        # "We could not look" is not "there is nothing": no empty flag is set.
        assert "empty" not in result, result
        assert not result.get("matches")
        assert not result.get("candidates")
        assert not result.get("buildable_dishes")
    # Both halves of the recommendation keep their own cause.
    sources = results[-1]["partial_sources"]
    assert sources["dishes"]["code"] == "INDEX_MISSING"
    assert sources["products"]["reason"] == "INDEX_MISSING"


def test_every_failed_and_empty_read_reports_which_filters_it_applied(reads):
    results = serve(
        reads,
        lookups=[Lookup("product", "可乐")],
        queries=[Query("recipe", "番茄炒蛋"), Query("recommend", "番茄炒蛋")],
    )
    assert len(results) == 3
    for result in results:
        assert result["status"] in ("completed", "failed")
        assert "filters_applied" in result


def test_a_read_that_ran_and_matched_nothing_is_empty_not_failed(reads):
    results = serve(
        reads,
        lookups=[Lookup("product", "键盘")],
        queries=[Query("recipe", "键盘"), Query("recommend", "键盘")],
    )
    assert len(results) == 3
    for result in results:
        assert result["status"] == "completed", result
        assert result["empty"] is True, result


def test_a_completed_recommendation_reports_both_sources(reads):
    (result,) = serve(reads, queries=[Query("recommend", "番茄炒蛋")])
    assert result["status"] == "completed"
    assert set(result["partial_sources"]) == {"dishes", "products"}
    assert result["stock_verified"] is False
    # Each half says how many rows it contributed, not just that it ran.
    assert result["partial_sources"]["dishes"]["hits"] == len(result["buildable_dishes"])
    assert result["partial_sources"]["products"]["hits"] == len(result["sellable_products"])
    assert result["sellable_products"][0]["sku_id"]


def test_a_recommendation_row_keeps_the_retrieval_metadata(reads):
    """The retrieval evidence reaches the model, not just the row's name.

    Driven with a real hit shape so the assertion is about what the read port
    carries, not about which route happened to run in this deployment.
    """
    dish_hit = {
        "kind": "dish",
        "target_id": "dish-fanqie-chao-dan",
        "name": "番茄炒蛋",
        "match_kind": "fuzzy",
        "evidence": ["菜名：番茄炒蛋", "匹配方式：lexical/vector"],
        "review_status": "unreviewed",
        "stock_verified": False,
        "unknown_constraints": ["taste"],
    }
    dishes = {
        "status": "ok",
        "retrieval_mode": "hybrid",
        "fallback_reason": None,
        "index_version": "idx-test",
        "filters_applied": {"excluded_ingredient_ids": ["peanut"]},
        "hits": [dish_hit],
        "empty": False,
    }
    result = reads._recommend_from_retrieval("番茄炒蛋", dishes, None)
    row = result["buildable_dishes"][0]
    assert row["match_kind"] == "fuzzy"
    assert row["evidence"] == dish_hit["evidence"]
    assert row["unknown_constraints"] == ["taste"]
    assert row["stock_verified"] is False
    # The unified retrieval fields survive the combination of the two sources.
    assert result["filters_applied"] == {"excluded_ingredient_ids": ["peanut"]}
    assert result["retrieval_mode"] == "hybrid"
    assert result["index_version"] == "idx-test"
    # One source ran and the other did not: usable, but never a clean success.
    assert result["retrieval_status"] == "degraded"
    assert result["status"] == "completed"
    assert result["partial_sources"]["products"]["status"] == "unavailable"


def test_the_open_recommendation_does_not_claim_the_dishes_can_be_covered(reads):
    (result,) = serve(reads, queries=[Query("recommend")])
    assert result["status"] == "completed"
    assert result["exploration"] is True
    assert result["stock_verified"] is False
    assert "可配齐" not in result["note"]
    # A generated plan is weaker than a verified purchase, and the note says so.
    assert "库存" in result["note"]
    assert "预算" in result["note"]


# ------------------------------------------------- the buildable-dish scan


def test_the_buildable_scan_has_no_first_twenty_blind_spot(db_session):
    dishes = load_templates(db_session)
    assert len(dishes) > 20, "the fixture is too small for this to prove anything"
    planner = TemplatePlanService(db_session, STORE, ZONE)
    found = planner.suggest_buildable_dishes(limit=10_000)
    found_ids = {row["dish_id"] for row in found}
    assert found_ids, found
    tail_ids = {d.get("dish_id") for d in dishes[20:]}
    assert found_ids & tail_ids, "only the first 20 dishes were examined"
    # Nothing was cut short, so the result is not reported as incomplete.
    assert planner.last_suggest_scan_exhausted is False


def test_a_cut_short_scan_is_reported_as_incomplete(db_session):
    planner = TemplatePlanService(db_session, STORE, ZONE)
    planner.suggest_buildable_dishes(limit=10_000, scan=5)
    assert planner.last_suggest_scan_exhausted is True
    planner.suggest_buildable_dishes(limit=100_000, deadline_expired=lambda: True)
    assert planner.last_suggest_scan_exhausted is True


def test_the_scan_reads_the_catalog_a_bounded_number_of_times(db_session):
    """One catalog snapshot per scan, not one query per ingredient per dish."""
    planner = TemplatePlanService(db_session, STORE, ZONE)
    planner.suggest_buildable_dishes(limit=1, scan=1)

    small = _count_selects(db_session, lambda: planner.suggest_buildable_dishes(
        limit=1, scan=1
    ))
    full = _count_selects(db_session, lambda: planner.suggest_buildable_dishes(
        limit=10_000
    ))
    assert full <= 8, full
    assert full <= small + 2, (small, full)


def test_the_catalog_snapshot_does_not_outlive_the_scan(db_session):
    planner = TemplatePlanService(db_session, STORE, ZONE)
    planner.suggest_buildable_dishes(limit=1)
    assert isinstance(planner.catalog, CatalogService)
    # And the real catalog still answers normally afterwards.
    assert planner.resolve_sku_for_ingredient("tomato")


def test_the_scan_honours_a_stated_exclusion(db_session):
    planner = TemplatePlanService(db_session, STORE, ZONE)
    found = planner.suggest_buildable_dishes(limit=10_000, excluded_ingredients=["egg"])
    assert found
    assert "番茄炒蛋" not in {row["name"] for row in found}


def test_the_scan_resolves_the_same_skus_as_the_real_catalog(db_session):
    """The snapshot changes *where* candidates come from, not which one wins."""
    planner = TemplatePlanService(db_session, STORE, ZONE)
    catalog = planner.catalog
    sku = planner.resolve_sku_for_ingredient("tomato")
    assert sku is not None
    planner.suggest_buildable_dishes(limit=1)
    assert planner.resolve_sku_for_ingredient("tomato")["sku_id"] == sku["sku_id"]


def _count_selects(session, call) -> int:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements)

"""Offline probes for defects found during the September 15 review.

Retargeted onto the one chain. Three probes only made sense against the retired
tool gate and are retired with their subject:

* "search then prepare is not discarded" — the turn now ends with a real
  retrieval followed by a compiled mutation; covered end to end by
  ``test_semantic_pipeline.py``;
* "invalid attempts consume the tool budget" — the budget now counts *model*
  calls in the loop, covered by ``test_agent_loop.py`` and the deadline suites;
* "displayed candidates are not user selections" — deliberately inverted by the
  new design: a candidate the server really retrieved *is* referenceable by the
  model, and the model decides. Nothing is selected without a mutation.

What stays here is the shared planner contract: whatever the model proposes, the
planner still receives server-owned arguments and returns validated metadata.
"""

from __future__ import annotations


def test_a_validated_mutation_compiles_to_planner_arguments():
    """The boundary's own output shape: server-owned values, no money field."""
    from app.agent.protocol import CandidateRef, Mutation
    from app.agent.tools.change_plan import compile_internal_args

    candidate = CandidateRef(
        ref="d1", kind="dish", target_id="dish-fanqie-chao-dan", name="番茄炒蛋"
    )
    mutation = Mutation(verb="add", candidate_ref="d1", name="番茄炒蛋")

    args = compile_internal_args(
        mutation,
        candidate,
        people=2,
        budget_fen=None,
        excluded_ingredients=["peanut"],
        operation="append",
    )

    assert args["target_kind"] == "dish"
    assert args["target_id"] == "dish-fanqie-chao-dan"
    assert args["operation"] == "append"
    assert args["people"] == 2
    assert args["exclude_ingredients"] == ["peanut"]
    assert "budget_fen" not in args


def test_an_absent_headcount_is_not_invented_for_the_planner():
    """No stated headcount means the planner falls back itself, not the agent."""
    from app.agent.protocol import CandidateRef, Mutation
    from app.agent.tools.change_plan import compile_internal_args

    candidate = CandidateRef(ref="d1", kind="dish", target_id="dish-x", name="某菜")
    args = compile_internal_args(
        Mutation(verb="add", candidate_ref="d1", name="某菜"),
        candidate,
        people=None,
        budget_fen=None,
        excluded_ingredients=[],
        operation="append",
    )
    assert "people" not in args


def test_a_schema_invalid_headcount_never_reaches_the_planner(db_session, monkeypatch):
    """``people=True`` is truthy everywhere on the way in and still refused.

    A bool headcount is refused by ``parse_proposal``, so this boundary is what
    stands between a malformed argument that got in another way and a real plan
    build. A rejected payload must not call the planner — and a well-formed one
    must, which is what keeps the first half from passing for the wrong reason.
    """
    from app.agent.protocol import CandidateSet, Mutation
    from app.agent.tools import change_plan
    from app.agent.tools.change_plan import PlanChangeExecutor
    from app.models.session import GuideSession

    calls = []

    def planner(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "error", "code": "PLANNER_STUB", "message": "stub"}

    monkeypatch.setattr(change_plan, "guarded_prepare_purchase_plan", planner)

    session = GuideSession(
        session_id="sess-schema-guard",
        owner_id="owner-test",
        entry_context_json="{}",
    )
    db_session.add(session)
    db_session.commit()
    candidates = CandidateSet()
    row = candidates.allocate("product", "demo:cola-330ml", "可乐 330毫升")
    executor = PlanChangeExecutor(db_session, "owner-test")

    def prepare(people):
        return executor.prepare(
            state=None,
            mutation=Mutation(verb="add", candidate_ref=row.ref, name=row.name, people=people),
            candidates=candidates,
            store="store-demo-01",
            zone="zone-default",
        )

    refused = prepare(True)
    assert calls == []
    assert refused["status"] == "failed"
    assert refused["code"] == "INVALID_ARGS"
    assert "people" in refused["message"]
    assert session.current_task_id is None

    # The same mutation with a real headcount does reach the planner, so the
    # refusal above is the schema check and not an earlier dead end.
    reached = prepare(2)
    assert len(calls) == 1
    assert reached["code"] == "PLANNER_STUB"


def test_plan_tool_preserves_validated_item_metadata(db_session):
    from app.agent.tools.prepare_purchase_plan import prepare_purchase_plan
    from app.agent.tools.search_dishes import search_dishes
    from app.services.template_matcher import get_template_by_id
    from app.services.template_plan_service import TemplatePlanService

    search = search_dishes(db_session, query="番茄炒蛋")
    dish_id = search["candidates"][0]["dish_id"]
    dish = get_template_by_id(db_session, dish_id)
    original = TemplatePlanService(
        db_session, "store-demo-01", "zone-default",
    ).validate_template_plan(dish, 2)
    result = prepare_purchase_plan(
        db_session, store_id="store-demo-01", delivery_zone_id="zone-default",
        dish_id=dish_id, people=2,
    )
    assert result["status"] == "ok"
    for before, after in zip(original["items"], result["items"], strict=True):
        for field in (
            "image_path", "image_kind", "spec_quantity", "spec_unit",
            "max_addable_quantity", "recommended_quantity", "ingredient_key",
        ):
            if field in before:
                assert field in after, f"Validated field lost: {field}"
                assert after[field] == before[field]

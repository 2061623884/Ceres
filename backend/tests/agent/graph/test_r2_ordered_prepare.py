"""R2 ordered multi-mutation prepare tests.

Target: ``PlanChangeExecutor.prepare_many`` — the pure, read-only prepare of an
already-authorised batch of mutations. These tests use a real seeded SQLite
database (catalog + store offers) so the shared domain merge/quantity rules run
for real, and a SQL listener that proves the prepare phase issues no DML.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import event, text

from app.agent.authorization import authorize_mutations
from app.agent.protocol import (
    CandidateSet,
    Mutation,
    SemanticProposal,
    SemanticProtocolError,
    Understanding,
)
from app.agent.state import TaskState
from app.agent.tools.change_plan import PlanChangeExecutor
from app.models.session import GuideSession, GuideTask
from app.schemas.goal import Goal, GoalCandidate, GoalChanges, TurnDecision

OWNER = "r2-prep-owner"
SESSION = "r2-prep-session"
TASK = "r2-prep-task"
STORE = "store-demo-01"
ZONE = "zone-default"
SKU = "demo:flour-all-purpose-500g"
NAME = "中筋面粉 500克"
GROUP = f"product:{SKU}"


def _plan() -> dict:
    """A minimal but real single-row product plan (offer-backed SKU)."""
    return {
        "plan_id": "plan-r2-prep",
        "plan_version": 1,
        "mode": "bundle",
        "items": [
            {
                "sku_id": SKU,
                "quantity": 2,
                "recommended_quantity": 2,
                "quantity_source": "recommended",
                "role": "required",
                "selected": True,
                "group_id": GROUP,
                "target_kind": "product",
                "target_id": SKU,
                "availability": "available",
                "unit_price_fen": 890,
                "max_addable_quantity": 9,
                "added_quantity": 0,
                "shortfall_quantity": 0,
                "required_item_id": GROUP,
            }
        ],
        "targets": [
            {
                "group_id": GROUP,
                "kind": "product",
                "target_id": SKU,
                "name": NAME,
                "people": None,
                "people_source": "recommended",
            }
        ],
        "coverage_mode": "full",
        "coverage_intent": "partial_ok",
        "gaps": [],
        "can_confirm": True,
        "selected_total_fen": 1780,
        "total_price_fen": 1780,
        "outstanding_total_fen": 1780,
        "validation_status": "passed",
    }


@pytest.fixture()
def prepare_env(db_session):
    db = db_session
    db.add(
        GuideSession(
            session_id=SESSION,
            owner_id=OWNER,
            current_task_id=TASK,
            session_version=3,
            entry_context_json="{}",
        )
    )
    db.add(
        GuideTask(
            task_id=TASK,
            session_id=SESSION,
            owner_id=OWNER,
            intent="purchase",
            state_version=5,
            status="active",
            plan_json=json.dumps(_plan()),
            requirements_json=json.dumps({"people": 2}),
        )
    )
    db.commit()

    executor = PlanChangeExecutor(db, OWNER)
    state = TaskState.from_db(db.get(GuideTask, TASK), {})
    candidates = CandidateSet()
    item = candidates.allocate("item", SKU, NAME, group_id=GROUP, target_kind="product")
    other_sku = "demo:sugar-white-500g"
    other = candidates.allocate(
        "item", other_sku, "白砂糖 500克", group_id=f"product:{other_sku}", target_kind="product"
    )
    return {
        "db": db,
        "executor": executor,
        "state": state,
        "candidates": candidates,
        "item": item,
        "other": other,
    }


def _quantity_mutation(item, mode: str, value: int) -> Mutation:
    return Mutation(
        verb="change",
        candidate_ref=item.ref,
        name=item.name,
        field="quantity",
        quantity_mode=mode,
        quantity_value=value,
    )


def _decision(
    *,
    focus_kind: str = "none",
    focus_ref: str | None = None,
    changed_fields: list[str] | None = None,
    candidate: GoalCandidate | None = None,
) -> TurnDecision:
    return TurnDecision(
        route="mutation",
        mutation_action="apply_mutation",
        readiness="ready",
        write_blocked=False,
        reason_code="test",
        relation="amend",
        focus_kind=focus_kind,
        focus_ref=focus_ref,
        changed_fields=list(changed_fields or ["quantity"]),
        candidate=candidate,
    )


def _proposal(mutations: list[Mutation], decision: TurnDecision) -> SemanticProposal:
    return SemanticProposal(
        understanding=Understanding(speech_act="request_action", goal_relation="amend", changes=GoalChanges()),
        mutations=mutations,
    )


def _dml_collector(engine):
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if head in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return statements, lambda: event.remove(engine, "before_cursor_execute", _record)


# --------------------------------------------------------------- the happy path


def test_authorized_same_row_quantity_batch_keeps_order_and_projects_plan(prepare_env):
    env = prepare_env
    item = env["item"]
    mutations = [
        _quantity_mutation(item, "delta", 1),  # 2 -> 3
        _quantity_mutation(item, "delta", 1),  # 3 -> 4 (on the projected plan)
    ]
    decision = _decision(focus_kind="plan_target", focus_ref=item.ref)
    authorized, refusals, conflict = authorize_mutations(
        decision, _proposal(mutations, decision), env["candidates"]
    )
    assert refusals == []
    assert conflict is None
    assert [m.quantity_value for m in authorized] == [1, 1]
    assert len(authorized) == 2

    steps = env["executor"].prepare_many(
        state=env["state"],
        mutations=authorized,
        candidates=env["candidates"],
        store=STORE,
        zone=ZONE,
    )
    assert [step["step_index"] for step in steps] == [0, 1]
    assert all(step["status"] == "staged" for step in steps)
    # The second step is built on the first step's virtual plan, not the DB row.
    assert steps[0]["plan_after"]["items"][0]["quantity"] == 3
    assert steps[1]["plan_after"]["items"][0]["quantity"] == 4
    assert steps[0]["mutation"]["quantity_value"] == 1
    assert steps[1]["mutation"]["quantity_value"] == 1
    assert steps[0]["plan_patch"]["items"][0]["quantity"] == 3
    assert steps[1]["plan_patch"]["items"][0]["quantity"] == 4

    # The caller's state is untouched by the pure prepare.
    assert env["state"].plan["items"][0]["quantity"] == 2


def test_single_mutation_prepare_many_matches_single_prepare(prepare_env):
    env = prepare_env
    item = env["item"]
    mutation = _quantity_mutation(item, "delta", 1)
    steps = env["executor"].prepare_many(
        state=env["state"],
        mutations=[mutation],
        candidates=env["candidates"],
        store=STORE,
        zone=ZONE,
    )
    single = env["executor"].prepare(
        state=env["state"], mutation=mutation, candidates=env["candidates"], store=STORE, zone=ZONE
    )
    assert len(steps) == 1
    # Same payload as the single prepare: no regression for the one-step batch.
    for key, value in single.items():
        assert steps[0][key] == value


def test_single_add_step_projects_merged_plan_without_dml(prepare_env):
    env = prepare_env
    db = env["db"]
    product = env["candidates"].allocate(
        "product", env["other"].target_id, env["other"].name, target_kind="product"
    )
    mutation = Mutation(verb="add", candidate_ref=product.ref, name=product.name)
    statements, remove_listener = _dml_collector(db.get_bind())
    try:
        steps = env["executor"].prepare_many(
            state=env["state"],
            mutations=[mutation],
            candidates=env["candidates"],
            store=STORE,
            zone=ZONE,
        )
    finally:
        remove_listener()

    assert statements == []
    assert len(steps) == 1
    step = steps[0]
    assert step["status"] == "staged" and step["verb"] == "add"
    # apply_result inputs for the commit node are all present.
    for key in ("plan_result", "args", "operation", "switching"):
        assert key in step, key
    skus = {row["sku_id"] for row in step["plan_after"]["items"]}
    assert skus == {SKU, env["other"].target_id}
    assert step["plan_after"] is not step["plan_result"]


def test_prepared_steps_are_apply_ready_in_one_transaction(prepare_env):
    """The returned patches apply in order inside the caller's one transaction."""
    env = prepare_env
    db = env["db"]
    item = env["item"]
    mutations = [
        _quantity_mutation(item, "delta", 1),  # 2 -> 3
        _quantity_mutation(item, "delta", 1),  # 3 -> 4
    ]
    steps = env["executor"].prepare_many(
        state=env["state"],
        mutations=mutations,
        candidates=env["candidates"],
        store=STORE,
        zone=ZONE,
    )

    state = env["state"]
    for step in steps:
        state.plan = step["plan_patch"]
        state.state_version += 1
        state.to_db(db, expected_version=state.state_version - 1)
    db.commit()

    row = db.execute(
        text("SELECT plan_json, state_version FROM guide_tasks WHERE task_id = :t"),
        {"t": TASK},
    ).one()
    assert json.loads(row[0])["items"][0]["quantity"] == 4
    assert row[1] == 7  # 5 + one version per applied step


# ------------------------------------------------------------- original refusal


def test_shared_rule_refuses_two_different_rows(prepare_env):
    env = prepare_env
    mutations = [
        _quantity_mutation(env["item"], "delta", 1),
        _quantity_mutation(env["other"], "delta", 1),
    ]
    decision = _decision(focus_kind="none")
    authorized, refusals, conflict = authorize_mutations(
        decision, _proposal(mutations, decision), env["candidates"]
    )
    assert len(authorized) == 2
    # The existing rule refuses the compound edit whole; prepare_many is not reached.
    assert conflict == "MIXED_GOAL_CHANGES"


def test_shared_rule_refuses_two_adds(prepare_env):
    env = prepare_env
    goal = Goal(kind="meal_plan", target_name=NAME)
    candidate = GoalCandidate(ref="goal-1", goal=goal, relation="append", target_ref=env["item"].ref)
    decision = _decision(
        focus_kind="pending_goal",
        focus_ref=env["item"].ref,
        changed_fields=["quantity"],
        candidate=candidate,
    )
    adds = [
        Mutation(verb="add", candidate_ref=env["item"].ref, name=NAME),
        Mutation(verb="add", candidate_ref=env["item"].ref, name=NAME),
    ]
    authorized, refusals, conflict = authorize_mutations(
        decision, _proposal(adds, decision), env["candidates"]
    )
    assert conflict in {"GOAL_CHANGE_CONFLICT", "MIXED_GOAL_CHANGES"}


# --------------------------------------------------------------- purity / DML


def test_prepare_many_issues_no_dml_and_second_step_failure_leaves_db_untouched(prepare_env):
    env = prepare_env
    db = env["db"]
    item = env["item"]
    before_plan = json.dumps(env["state"].plan, sort_keys=True)
    before_version = env["state"].state_version

    mutations = [
        _quantity_mutation(item, "delta", 1),  # 2 -> 3, would be legal alone
        _quantity_mutation(item, "set", 99),  # out of range: > max_addable 9
    ]
    statements, remove_listener = _dml_collector(db.get_bind())
    try:
        # The listener really does see DML: prove it with a no-op update first.
        db.execute(text("UPDATE guide_tasks SET state_version = state_version WHERE 1 = 0"))
        probe = list(statements)
        statements.clear()
        assert len(probe) == 1 and probe[0].lstrip().upper().startswith("UPDATE")

        with pytest.raises(SemanticProtocolError) as exc:
            env["executor"].prepare_many(
                state=env["state"],
                mutations=mutations,
                candidates=env["candidates"],
                store=STORE,
                zone=ZONE,
            )
    finally:
        remove_listener()

    assert exc.value.code == "QUANTITY_OUT_OF_RANGE"
    assert exc.value.message.startswith("第 2 步：")
    # No insert/update/delete was issued by the whole prepare phase.
    assert statements == []

    # Nothing persisted, nothing changed in memory.
    db.rollback()
    row = db.execute(
        text("SELECT plan_json, state_version FROM guide_tasks WHERE task_id = :t"),
        {"t": TASK},
    ).one()
    assert json.dumps(json.loads(row[0]), sort_keys=True) == before_plan
    assert row[1] == before_version
    assert env["state"].plan["items"][0]["quantity"] == 2


def test_prepare_many_rolls_back_whole_batch_on_later_failure(prepare_env):
    """The first step is legal; the batch still returns nothing on failure."""
    env = prepare_env
    item = env["item"]
    mutations = [
        _quantity_mutation(item, "delta", 1),
        _quantity_mutation(item, "delta", 100),
    ]
    with pytest.raises(SemanticProtocolError) as exc:
        env["executor"].prepare_many(
            state=env["state"],
            mutations=mutations,
            candidates=env["candidates"],
            store=STORE,
            zone=ZONE,
        )
    assert exc.value.code == "QUANTITY_OUT_OF_RANGE"
    assert "第 2 步" in exc.value.message

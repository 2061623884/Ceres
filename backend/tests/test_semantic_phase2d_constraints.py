"""Phase 2d small-pack specification on real read and purchase paths."""

import json
import uuid

import pytest

from app.agent.protocol import CandidateSet, Query, SemanticProtocolError, parse_proposal
from app.agent.state import Requirements
from app.agent.tools.read import ReadTools
from app.agent.turn_primitives import TurnSnapshot, evaluate_gate
from app.core import database as db_module
from app.models.catalog import CatalogProduct
from app.models.session import GuideSemanticContext, GuideTask
from app.services.validation_context import ValidationContext
from support import create_session, post_turn
from support.semantic_agent import Continuation, request_amend, request_new
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize(
    "specification",
    [{"size": "large"}, {"brand": 123}, "small"],
)
def test_specification_rejects_values_outside_current_size_contract(specification):
    with pytest.raises(SemanticProtocolError) as error:
        parse_proposal({"constraints": {"specification": specification}})
    assert error.value.code == "MALFORMED_PROPOSAL"


def test_size_none_means_unstated():
    proposal = parse_proposal(
        {
            "lookups": [{"kind": "product", "query": "可乐"}],
            "constraints": {"specification": {"size": "none"}},
        }
    )

    assert proposal.lookups[0].specification == {}


def test_specification_clear_is_an_explicit_patch():
    proposal = parse_proposal({"constraints": {"clear": ["specification"]}})

    assert proposal.understanding.changes.clear == ["specification"]
    assert proposal.understanding.changes.set.stated() == {}


@pytest.mark.parametrize(
    "raw",
    [
        {
            "target": {"kind": "product", "intent": "buy", "name": "可乐"},
            "constraints": {"clear": ["specification"]},
        },
        {
            "lookups": [{"kind": "product", "query": "可乐"}],
            "constraints": {"clear": ["specification"]},
        },
        {
            "reads": [{"kind": "recommend", "topic": "饮料"}],
            "constraints": {"clear": ["specification"]},
        },
    ],
)
def test_specification_clear_cannot_be_combined_with_target_or_read(raw):
    with pytest.raises(SemanticProtocolError) as error:
        parse_proposal(raw)
    assert error.value.code == "UNSUPPORTED_OPERATION"


def test_small_pack_alone_makes_an_unnamed_meal_ready():
    decision = evaluate_gate(
        TurnSnapshot(turn_mode="active", message="小包装帮我配一餐"),
        parse_proposal(
            {
                "target": {"kind": "meal", "intent": "buy", "name": ""},
                "constraints": {"specification": {"size": "small"}},
            }
        ),
        CandidateSet(),
    )

    assert decision.route == "mutation"
    assert decision.readiness == "ready"
    assert decision.reason_code == "GOAL_READY"
    assert decision.missing_slots == []


def test_legacy_product_lookup_filters_to_real_small_packs(db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("RETRIEVAL_INDEX_DIR", "")
    get_settings.cache_clear()
    reads = ReadTools(
        db_session,
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )
    result = reads._query(
        Query(
            kind="recommend",
            query="可乐 330毫升",
            specification={"size": "small"},
        ),
        CandidateSet(),
    )
    assert result["filters_applied"]["specification"] == {"size": "small"}
    assert result["fallback_reason"] == "no_published_index"
    ids = [row["sku_id"] for row in result["sellable_products"]]
    assert ids
    rows = {
        row.sku_id: row
        for row in db_session.query(CatalogProduct).filter(CatalogProduct.sku_id.in_(ids))
    }
    context = ValidationContext.from_requirements(
        Requirements(specification={"size": "small"}),
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )
    assert all(
        context.matches_spec(
            {"spec_quantity": rows[sku_id].spec_quantity, "spec_unit": rows[sku_id].spec_unit}
        )
        for sku_id in ids
    )
    get_settings.cache_clear()


def test_indexed_exact_product_filter_is_reported_as_specification_conflict(
    indexed_client, semantic_provider, monkeypatch
):
    observed = []
    original = ReadTools.serve

    def record(self, proposal, candidates, *, lookup_limit):
        results = original(self, proposal, candidates, lookup_limit=lookup_limit)
        observed.extend(results)
        return results

    monkeypatch.setattr(ReadTools, "serve", record)
    semantic_provider(
        [
            {
                "lookups": [{"kind": "product", "query": "全脂牛奶 1升"}],
                "constraints": {"specification": {"size": "small"}},
            },
            Continuation(lambda request: {"reply": "查询完成。"}),
        ]
    )
    sid = create_session(indexed_client)
    response = post_turn(indexed_client, sid, "查一下全脂牛奶")
    assert response.status_code == 200, response.json()
    result = observed[0]
    assert result["conflict"]["code"] == "CONSTRAINT_CONFLICT", result
    assert result["conflict"]["constraint_fields"] == ["specification"]
    assert "小包装" in result["conflict"]["message"]
    assert "下架" not in result["conflict"]["message"]
    assert result["matches"] == []
    assert "dropped_exact_match" not in result
    assert result["filters_applied"]["specification"] == {"size": "small"}


def test_saved_small_read_condition_reaches_a_later_purchase(indexed_client, semantic_provider):
    provider = semantic_provider(
        [
            {
                "lookups": [{"kind": "product", "query": "全脂牛奶 1升"}],
                "constraints": {"specification": {"size": "small"}},
            },
            Continuation(lambda request: {"reply": "查到了。"}),
            {
                **request_new("product", "可乐"),
                "lookups": [{"kind": "product", "query": "可乐"}],
            },
        ]
    )
    sid = create_session(indexed_client)
    read_response = post_turn(indexed_client, sid, "查一下全脂牛奶")
    assert read_response.status_code == 200, read_response.json()
    read = read_response.json()
    assert read["plan"] is None
    first_read = provider.requests[1]["query_results"][0]
    assert first_read["filters_applied"]["specification"] == {"size": "small"}
    assert first_read["conflict"]["constraint_fields"] == ["specification"]

    buy_response = post_turn(indexed_client, sid, "买可乐", read)
    assert buy_response.status_code == 200, buy_response.json()
    bought = buy_response.json()
    assert bought["route"] == "prepare", bought
    assert [row["sku_id"] for row in bought["plan"]["items"]] == ["demo:cola-330ml"]
    assert provider.requests[2]["requirements"] == {"specification": {"size": "small"}}

    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, bought["task_id"])
        assert json.loads(task.requirements_json)["specification"] == {"size": "small"}
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_clearing_system_small_condition_removes_task_and_session_inheritance(
    indexed_client, semantic_provider
):
    provider = semantic_provider(
        [
            request_new(
                "dish",
                "",
                constraints={
                    "specification": {"size": "small"},
                    "excluded_ingredients": ["鸡蛋"],
                },
            ),
            request_amend(changes={"clear": ["specification"]}),
            {"lookups": [{"kind": "product", "query": "全脂牛奶 1升"}]},
            Continuation(lambda request: {"reply": "查到了。"}),
            {
                **request_new("product", "全脂牛奶 1升", relation="append"),
                "lookups": [{"kind": "product", "query": "全脂牛奶 1升"}],
            },
            Continuation(lambda request: {"reply": "已加入清单。"}),
        ]
    )
    sid = create_session(indexed_client)
    first_response = post_turn(indexed_client, sid, "帮我配一餐，选小包装并避开鸡蛋")
    assert first_response.status_code == 200, first_response.json()
    first = first_response.json()
    assert first["route"] == "prepare", first
    assert first["plan"]["targets"][0]["selection_goal"]["constraints"][
        "specification"
    ] == {"size": "small"}
    with db_module.SessionLocal() as db:
        first_task = db.get(GuideTask, first["task_id"])
        first_requirements = json.loads(first_task.requirements_json)
    assert first_requirements["specification"] == {"size": "small"}

    cleared_response = post_turn(indexed_client, sid, "不限包装大小了", first)
    assert cleared_response.status_code == 200, cleared_response.json()
    cleared = cleared_response.json()
    assert cleared["route"] == "prepare", cleared
    assert cleared["plan"]["targets"][0]["selection_goal"]["constraints"][
        "specification"
    ] == {}
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, cleared["task_id"])
        requirements = json.loads(task.requirements_json)
        context = db.get(GuideSemanticContext, sid)
        session_constraints = json.loads(context.context_json).get("session_constraints", {})
    assert requirements.get("specification", {}) == {}
    assert session_constraints.get("specification", {}) == {}

    read_response = post_turn(indexed_client, sid, "查一下全脂牛奶 1升", cleared)
    assert read_response.status_code == 200, read_response.json()
    read = provider.requests[-1]["query_results"][0]
    assert read["filters_applied"]["specification"] == {}
    assert read["matches"]
    milk_id = read["matches"][0]["target_id"]

    bought_response = post_turn(indexed_client, sid, "再买全脂牛奶 1升", read_response.json())
    assert bought_response.status_code == 200, bought_response.json()
    bought = bought_response.json()
    assert bought["route"] == "prepare", bought
    assert milk_id in [row["sku_id"] for row in bought["plan"]["items"]]
    assert provider.requests[-2]["requirements"].get("specification", {}) == {}
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, bought["task_id"])
        assert json.loads(task.requirements_json).get("specification", {}) == {}
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_cleared_small_spec_is_not_restored_when_pending_switch_becomes_meal(
    indexed_client, semantic_provider
):
    provider = semantic_provider(
        [
            {
                **request_new(
                    "product",
                    "可乐 330毫升",
                    constraints={"specification": {"size": "small"}},
                ),
                "lookups": [{"kind": "product", "query": "可乐 330毫升"}],
            },
            request_new("category", "", relation="switch"),
            request_amend(changes={"clear": ["specification"]}),
            request_new("dish", ""),
        ]
    )
    sid = create_session(indexed_client)
    first_response = post_turn(indexed_client, sid, "买可乐330毫升，小包装")
    assert first_response.status_code == 200, first_response.json()
    first = first_response.json()
    assert first["route"] == "prepare", first
    old_task_id = first["task_id"]

    pending_response = post_turn(indexed_client, sid, "换成某个类别", first)
    assert pending_response.status_code == 200, pending_response.json()
    pending = pending_response.json()
    assert pending["route"] == "clarify", pending
    assert pending["missing_slots"] == ["category"]
    with db_module.SessionLocal() as db:
        old_task = db.get(GuideTask, old_task_id)
        old_requirements = json.loads(old_task.requirements_json)
        context = json.loads(db.get(GuideSemanticContext, sid).context_json)
    assert old_requirements["specification"] == {"size": "small"}
    candidate = context["goal_candidate"]
    assert candidate["relation"] == "switch"
    assert candidate["goal"]["kind"] == "category_purchase"
    assert candidate["goal"]["constraints"]["specification"] == {"size": "small"}

    cleared_response = post_turn(indexed_client, sid, "取消小包装要求", pending)
    assert cleared_response.status_code == 200, cleared_response.json()
    cleared = cleared_response.json()
    assert cleared["route"] == "clarify", cleared
    assert cleared["missing_slots"] == ["category"]
    with db_module.SessionLocal() as db:
        old_task = db.get(GuideTask, old_task_id)
        old_requirements = json.loads(old_task.requirements_json)
        context = json.loads(db.get(GuideSemanticContext, sid).context_json)
    assert old_requirements["specification"] == {"size": "small"}
    assert context.get("session_constraints", {}).get("specification", {}) == {}
    assert context["goal_candidate"]["goal"]["constraints"]["specification"] == {}

    meal_response = post_turn(indexed_client, sid, "帮我配一餐", cleared)
    assert meal_response.status_code == 200, meal_response.json()
    meal = meal_response.json()
    assert meal["route"] == "prepare", meal
    assert meal["status"] == meal["answer_status"] == "awaiting_confirmation"
    assert meal["task_id"] != old_task_id
    assert meal["plan"]["targets"][0]["selection_goal"]["constraints"][
        "specification"
    ] == {}
    with db_module.SessionLocal() as db:
        old_task = db.get(GuideTask, old_task_id)
        new_task = db.get(GuideTask, meal["task_id"])
        assert json.loads(old_task.requirements_json)["specification"] == {"size": "small"}
        assert json.loads(new_task.requirements_json).get("specification", {}) == {}
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    assert provider.remaining() == 0


@pytest.mark.parametrize("channel", ["http", "chat"])
def test_confirmation_rechecks_persisted_small_specification_without_cart_write(
    indexed_client, semantic_provider, channel
):
    from test_confirmation import _confirm
    from test_phase2b_chat_confirmation import _cart_quantities, _error, _persisted

    provider = semantic_provider(
        [
            {
                **request_new(
                    "product",
                    "可乐 330毫升",
                    constraints={"specification": {"size": "small"}},
                ),
                "lookups": [{"kind": "product", "query": "可乐 330毫升"}],
            }
        ]
    )
    sid = create_session(indexed_client)
    prepared_response = post_turn(indexed_client, sid, "买可乐 330毫升，要小包装")
    assert prepared_response.status_code == 200, prepared_response.json()
    prepared = prepared_response.json()
    assert prepared["route"] == "prepare", prepared
    assert [row["sku_id"] for row in prepared["plan"]["items"]] == ["demo:cola-330ml"]

    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, prepared["task_id"])
        assert json.loads(task.requirements_json)["specification"] == {"size": "small"}
        product = db.get(CatalogProduct, "demo:cola-330ml")
        product.spec_quantity = 1000
        product.spec_unit = "ml"
        db.commit()

    before = _persisted(sid, prepared["task_id"])
    if channel == "http":
        rejected = _confirm(
            indexed_client, prepared["task_id"], prepared["plan"], prepared["state_version"]
        )
        assert rejected.status_code == 422, rejected.text
        error = rejected.json()["error"]
    else:
        request_id = str(uuid.uuid4())
        provider = semantic_provider([{"plan_act": "confirm"}])
        error, _ = _error(
            indexed_client, sid, "加入购物车", prepared, request_id=request_id
        )
        failed = _persisted(sid, prepared["task_id"])
        assert failed["receipts"][-1]["request_id"] == request_id
        assert failed["receipts"][-1]["status"] == "failed"
        receipt_count = len(failed["receipts"])
        replay, _ = _error(
            indexed_client, sid, "加入购物车", prepared, request_id=request_id
        )
        assert replay["code"] == error["code"]
        assert len(_persisted(sid, prepared["task_id"])["receipts"]) == receipt_count
        assert len(provider.requests) == 1

    assert error["code"] == "CONSTRAINT_UNSATISFIED"
    assert "小包装" in error["message"]
    assert "1000.0ml" in error["message"]
    after = _persisted(sid, prepared["task_id"])
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert _cart_quantities(indexed_client) == {}


def test_appending_new_small_pack_constraint_keeps_existing_plan_unchanged(
    indexed_client, semantic_provider
):
    provider = semantic_provider(
        [
            {
                **request_new("product", "可乐 330毫升"),
                "lookups": [{"kind": "product", "query": "可乐 330毫升"}],
            },
            {
                **request_new(
                    "product",
                    "全脂牛奶 1升",
                    relation="append",
                    constraints={"specification": {"size": "small"}},
                ),
                "lookups": [{"kind": "product", "query": "全脂牛奶 1升"}],
            },
        ]
    )
    sid = create_session(indexed_client)
    first_response = post_turn(indexed_client, sid, "买可乐 330毫升")
    assert first_response.status_code == 200, first_response.json()
    first = first_response.json()
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, first["task_id"])
        plan_before = task.plan_json
        requirements_before = task.requirements_json

    second_response = post_turn(
        indexed_client,
        sid,
        "再买全脂牛奶 1升，要小包装",
        first,
    )
    assert second_response.status_code == 200, second_response.json()
    second = second_response.json()
    assert second["plan_effect"] == "keep"
    assert second["task_id"] == first["task_id"]
    assert any(row["code"] == "UNSUPPORTED_OPERATION" for row in second["action_results"])
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, first["task_id"])
        assert task.plan_json == plan_before
        assert task.requirements_json == requirements_before
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    assert provider.remaining() == 0

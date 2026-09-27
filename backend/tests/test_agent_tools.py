"""The structural boundary of the plan tool.

The retired ``ToolGate`` enforced three things: a per-turn call budget, a closed
set of tool names, and a strict argument schema. Only the third survives, and it
now guards the one mutation boundary (``PlanChangeExecutor`` validates the
compiled call through the shared validator). The other two are replaced by:

* the loop's own model-call budget (``app/agent/loop.py``, covered by
  ``test_agent_loop.py`` and the deadline/pipeline suites);
* the proposal protocol, which has a closed set of verbs and fields rather than a
  set of tool names (covered by ``test_semantic_pipeline.py`` and
  ``test_semantic_acceptance_edges.py``).

What is tested here is the piece that moved: the shared validator, which is the
only remaining structural check between a proposal and a planner call.
"""

from __future__ import annotations

import pytest

from app.agent.tools.schemas import PREPARE_PURCHASE_PLAN_INPUT_SCHEMA
from app.agent.tools.validation import MAX_PEOPLE, validate_json_object

SCHEMA = PREPARE_PURCHASE_PLAN_INPUT_SCHEMA


def test_a_well_formed_call_is_accepted():
    assert validate_json_object(
        SCHEMA,
        {
            "target_kind": "dish",
            "target_id": "dish-fanqie-chao-dan",
            "people": 2,
            "operation": "append",
            "exclude_ingredients": ["peanut"],
        },
    ) is None


def test_a_non_object_payload_is_refused():
    assert validate_json_object(SCHEMA, ["not", "an", "object"]) is not None


def test_an_unknown_field_is_refused():
    """The schema is closed: a field the planner does not know is an error."""
    error = validate_json_object(SCHEMA, {"target_kind": "dish", "price_fen": 1200})
    assert error is not None and "price_fen" in error


def test_a_value_outside_the_enum_is_refused():
    error = validate_json_object(SCHEMA, {"target_kind": "coupon"})
    assert error is not None and "target_kind" in error


def test_a_boolean_is_not_an_integer_count():
    """``people=True`` must never reach the planner as one person."""
    error = validate_json_object(SCHEMA, {"people": True})
    assert error is not None and "people" in error


def test_a_count_over_the_hard_ceiling_is_refused():
    error = validate_json_object(SCHEMA, {"people": MAX_PEOPLE + 1})
    assert error is not None and "people" in error


def test_a_count_below_the_minimum_is_refused():
    error = validate_json_object(SCHEMA, {"quantity": 0})
    assert error is not None and "quantity" in error


def test_an_array_with_a_non_string_element_is_refused():
    error = validate_json_object(SCHEMA, {"exclude_ingredients": ["peanut", 7]})
    assert error is not None and "exclude_ingredients" in error


def test_an_array_with_an_empty_string_is_refused():
    error = validate_json_object(SCHEMA, {"exclude_ingredients": ["  "]})
    assert error is not None and "exclude_ingredients" in error


@pytest.mark.parametrize("key", ["target_id", "target_name", "dish_id"])
def test_a_required_non_empty_string_field_rejects_an_empty_value(key):
    error = validate_json_object(SCHEMA, {key: ""})
    assert error is not None and key in error


def test_the_schema_exposes_no_money_field():
    """Money is the server's, so the model-visible schema must not carry one."""
    assert "budget_fen" not in SCHEMA["properties"]
    assert "price_fen" not in SCHEMA["properties"]

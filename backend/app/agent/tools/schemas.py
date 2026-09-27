"""JSON Schema for the one plan tool the model may propose."""

from __future__ import annotations

from typing import Any

#: The one shopping tool. ``target_kind`` selects a recipe, a direct product or an
#: open scenario; ``operation`` says how the result relates to the plan the user
#: is already editing. No money field is exposed: the model states intent, the
#: server owns every price, pack size and stock number.
PREPARE_PURCHASE_PLAN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_kind": {
            "type": "string",
            "enum": ["dish", "product", "scenario"],
        },
        "target_id": {"type": "string", "minLength": 1},
        "target_name": {"type": "string", "minLength": 1},
        # Legacy alias: older callers used dish_id + required people.
        "dish_id": {"type": "string", "minLength": 1},
        "people": {"type": "integer", "minimum": 1},
        #: Pack count for a direct product request ("来两瓶可乐"). Counts are
        #: user-stated and clamped server-side; no price is accepted here.
        "quantity": {"type": "integer", "minimum": 1, "maximum": 99},
        "operation": {
            "type": "string",
            "enum": ["append", "replace", "resize"],
        },
        "exclude_ingredients": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
    },
    "required": [],
}

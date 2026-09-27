"""Structural validation of the closed plan-tool input schema.

The shared validator used by ``PlanChangeExecutor`` before it hands arguments
to the business services. It has no routing or persistence responsibility and
does not depend on the retired tool-call gate.
"""

from __future__ import annotations

from typing import Any

#: A hard ceiling that is not part of the model-visible schema: nobody cooks for
#: more people than this in the demo store.
MAX_PEOPLE = 50


def _is_int(value: Any) -> bool:
    # ``bool`` is a subclass of ``int``; ``people=True`` must never reach the planner.
    return isinstance(value, int) and not isinstance(value, bool)


def validate_json_object(schema: dict[str, Any], args: Any) -> str | None:
    """Validate ``args`` against the (small, closed) tool input schema.

    Returns an error string, or ``None`` when the payload is structurally valid.
    Every field is checked: type, range, enum membership, array element contents
    and extra keys.
    """
    if not isinstance(args, dict):
        return "tool arguments must be an object"
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args or args[key] is None:
            return f"missing required field: {key}"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(args) - set(properties))
        if extra:
            return f"unknown fields: {', '.join(extra)}"

    for key, value in args.items():
        if value is None:
            continue
        spec = properties.get(key)
        if spec is None:
            continue
        expected = spec.get("type")
        if expected == "string":
            if not isinstance(value, str):
                return f"{key} must be a string"
            if len(value) < int(spec.get("minLength", 0)):
                return f"{key} must not be empty"
            if "enum" in spec and value not in spec["enum"]:
                return f"{key} must be one of: {', '.join(str(v) for v in spec['enum'])}"
        elif expected == "integer":
            if not _is_int(value):
                return f"{key} must be an integer"
            if "minimum" in spec and value < int(spec["minimum"]):
                return f"{key} must be >= {spec['minimum']}"
            if "maximum" in spec and value > int(spec["maximum"]):
                return f"{key} must be <= {spec['maximum']}"
            if key == "people" and value > MAX_PEOPLE:
                return f"{key} must be <= {MAX_PEOPLE}"
        elif expected == "array":
            if not isinstance(value, list):
                return f"{key} must be an array"
            item_type = (spec.get("items") or {}).get("type")
            for element in value:
                if item_type == "string" and not isinstance(element, str):
                    return f"{key} must contain only strings"
                if isinstance(element, str) and not element.strip():
                    return f"{key} must not contain empty strings"
    return None


__all__ = ["MAX_PEOPLE", "validate_json_object"]

"""Extract JSON from model text responses."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model output, including fenced code blocks."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty model output")

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.IGNORECASE)
    if fence:
        parsed = json.loads(fence.group(1).strip())
        if isinstance(parsed, dict):
            return parsed

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        parsed = json.loads(stripped[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("no JSON object found in model output")

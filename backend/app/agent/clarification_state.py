"""Persistent clarification slot tracking."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingClarification:
    question_id: str
    question: str
    options: list[dict[str, str]] = field(default_factory=list)
    base_session_version: int = 0
    base_state_version: int = 0
    slot: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    people: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "options": self.options,
            "base_session_version": self.base_session_version,
            "base_state_version": self.base_state_version,
            "slot": self.slot,
            "candidates": self.candidates,
            "people": self.people,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PendingClarification | None:
        if not data:
            return None
        return cls(
            question_id=data.get("question_id", ""),
            question=data.get("question") or data.get("prompt", ""),
            options=data.get("options", []),
            base_session_version=data.get("base_session_version", 0),
            base_state_version=data.get("base_state_version", 0),
            slot=data.get("slot", ""),
            candidates=data.get("candidates", []),
            people=data.get("people"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> PendingClarification | None:
        if not raw:
            return None
        try:
            return cls.from_dict(json.loads(raw))
        except json.JSONDecodeError:
            return None

    def match_option(self, message: str) -> str | None:
        """Return matched option id when the user answers a pending question."""
        text = message.strip()
        if not text:
            return None
        for opt in self.options:
            opt_id = opt.get("id", "")
            label = opt.get("label", "")
            if opt_id and (text == opt_id or opt_id in text):
                return opt_id
            if label and (text == label or label in text):
                return opt_id
        if self.slot == "gap_fill_scope":
            if re.search(r"追加|加上|补", text):
                return "append"
            if re.search(r"另做|新清单|重新做|新的", text):
                return "new_plan"
        return None

    def match_candidate(self, message: str) -> dict[str, Any] | None:
        """Match user text to a stored dish candidate."""
        text = message.strip()
        if not text or not self.candidates:
            return None
        ordinal_patterns = [
            (re.compile(r"第?一|第一个|^1$"), 0),
            (re.compile(r"第?二|第二个|^2$"), 1),
            (re.compile(r"第?三|第三个|^3$"), 2),
            (re.compile(r"第?四|第四个|^4$"), 3),
            (re.compile(r"第?五|第五个|^5$"), 4),
        ]
        for pattern, idx in ordinal_patterns:
            if pattern.search(text) and idx < len(self.candidates):
                return self.candidates[idx]
        for candidate in self.candidates:
            name = candidate.get("name") or candidate.get("scenario") or ""
            if name and (name in text or text in name):
                return candidate
            for alias in candidate.get("aliases") or []:
                if alias and (alias in text or text in alias):
                    return candidate
        return None

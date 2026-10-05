"""Pinned Kev SystemOne service; three choices, no chat-model fallback."""
from typing import Literal
from functools import lru_cache

import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings

Decision = Literal["stay_current", "suggest_switch", "clarify"]
CRITERIA_VERSION = "ceres-service-v3.1"
# 01 observed 235.6–773ms. This bounds network/inference, not the 1s P95 target.
KEV_TIMEOUT_SECONDS = 3.0
INSTRUCTIONS = """Classify this turn using current_role, selected_object and recent_dialogue.
Keke handles shopping, product comparison, purchase lists. Momo handles specific placed orders,
order eligibility and after-sales actions. BOTH roles answer GENERAL store policies (returns,
refunds, delivery) and greetings. A product being considered is NOT a placed order.
The latest explicit new request overrides the old topic. Be conservative about switching.
For '取消一下': shopping-list context stays with Keke; placed-order context needs Momo;
with no resolvable object choose clarify. Questions about a general policy stay even when
they mention returns. Only classify; never act, invent an object or automatically switch."""
CRITERIA = {
    "stay_current": "Current role can handle it: shopping with Keke, specific orders with Momo, or GENERAL policies/greetings with either role.",
    "suggest_switch": "Clearly requires the OTHER role: specific placed-order work from Keke, or a NEW shopping request from Momo. Not general policy or ambiguous cancellation.",
    "clarify": "Intent/object is unresolved even with context, especially cancellation with no object. Ask in the current chat before choosing a service.",
}


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: Decision
    probabilities: dict[Decision, float] = Field(min_length=3, max_length=3)

    @field_validator("probabilities")
    @classmethod
    def valid_probabilities(cls, values):
        if any(not 0 <= value <= 1 for value in values.values()):
            raise ValueError("Kev probabilities must be between zero and one")
        return values


class Answers(BaseModel):
    service: ChoiceAnswer


class KevResponse(BaseModel):
    model: Literal["kev-latest"]
    answers: Answers


class KevUnavailable(Exception):
    """The network or documented external response contract failed."""


class KevProvider:
    def __init__(self):
        # Diagnosis measured ~799ms constructing this per turn on Windows.
        self.client = httpx.Client(timeout=KEV_TIMEOUT_SECONDS)

    def decide(self, state: dict) -> tuple[ChoiceAnswer, dict]:
        payload = {"state": state, "model": "kev-latest", "questions": {"service": {
            "type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}}}
        try:
            response = self.client.post(get_settings().kev_base_url.rstrip("/") + "/v1/systemone", json=payload)
            response.raise_for_status()
            raw = response.json()
            answer = KevResponse.model_validate(raw).answers.service
        except (httpx.HTTPError, ValueError) as exc:
            raise KevUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return answer, raw


@lru_cache(maxsize=1)
def get_kev_provider() -> KevProvider:
    return KevProvider()

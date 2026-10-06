"""Pinned Kev SystemOne service; three choices, no chat-model fallback."""
from typing import Literal
from functools import lru_cache

import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings

Decision = Literal["stay_current", "suggest_switch", "clarify"]
Capability = Literal["category_exploration", "purchase_modify", "facts_qa", "chat"]
CRITERIA_VERSION = "ceres-service-v3.2"
CAPABILITY_CRITERIA_VERSION = "ceres-guide-capabilities-v2"
# 01 observed 235.6–773ms. This bounds network/inference, not the 1s P95 target.
KEV_TIMEOUT_SECONDS = 3.0
INSTRUCTIONS = """Classify this turn using current_role, selected_object and recent_dialogue.
Keke handles shopping, product comparison, purchase lists. Momo handles specific placed orders,
order eligibility and after-sales actions. BOTH roles answer GENERAL store policies (returns,
refunds, delivery) and greetings. A product being considered is NOT a placed order.
The latest explicit new request overrides the old topic. Be conservative about switching.
Decide which SERVICE can continue, not whether its business action is fully specified.
Recent dialogue can resolve the service even when selected_object is null. If that dialogue
is about removing an item from a purchase list, Keke handles the next cancellation reply;
Keke can clarify the exact item/action within its own business turn.
For '取消一下': shopping-list context stays with Keke; placed-order context needs Momo;
with no resolvable object choose clarify. Questions about a general policy stay even when
they mention returns. Only classify; never act, invent an object or automatically switch."""
CRITERIA = {
    "stay_current": "Current role can handle it: shopping or purchase-list changes with Keke (including a short cancellation reply to list-removal dialogue, even without selected_object), specific orders with Momo, or GENERAL policies/greetings with either role. Business details may still need clarification within that role.",
    "suggest_switch": "Clearly requires the OTHER role: specific placed-order work from Keke, or a NEW shopping request from Momo. Not general policy or ambiguous cancellation.",
    "clarify": "The SERVICE needed is unresolved even with current role, selected object and dialogue. Cancellation with neither a purchase-list nor placed-order context needs clarification. Missing item details inside an already clear shopping service do not require service clarification.",
}
CAPABILITY_INSTRUCTIONS = """Classify the current Keke turn into exactly one capability using
the utterance, selected_object and recent dialogue. This is an internal capability choice;
do not choose or change the service role. Choose category_exploration when the user is
browsing, narrowing or comparing product/category candidates, including a broad shopping
category request such as “来点零食” before a specific product is selected. Choose
purchase_modify when the user explicitly wants to buy or prepare a purchase plan, including
a broad category request such as “买点饮料，两瓶，预算20元”; a specific product name is
not required. Choose facts_qa when the user asks for product, store or policy facts. Choose
chat only for greetings and ordinary conversation unrelated to supermarket shopping. A pending
question and its answer are part of the current request context. Only classify: never provide
business parameters, objects or authorization."""
CAPABILITY_CRITERIA = {
    "category_exploration": "用户提出宽泛品类购物请求（如「来点零食」）但尚未选定具体商品时的浏览、了解、缩小或比较品类及商品候选；包括继续回答选购中的类型或筛选问题。",
    "purchase_modify": "明确要买某宽泛品类或具体商品，或准备、修改购买方案、清单、数量、预算、选择项，或明确确认加购。",
    "facts_qa": "询问商品、门店或一般政策事实，需要依据业务数据或政策来源回答。",
    "chat": "问候或只用于与超市选购无关的交流。",
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


class CapabilityChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: Capability
    probabilities: dict[Capability, float] = Field(min_length=4, max_length=4)

    @field_validator("probabilities")
    @classmethod
    def valid_probabilities(cls, values):
        if any(not 0 <= value <= 1 for value in values.values()):
            raise ValueError("Kev probabilities must be between zero and one")
        return values


class CapabilityAnswers(BaseModel):
    capability: CapabilityChoiceAnswer


class CapabilityKevResponse(BaseModel):
    model: Literal["kev-latest"]
    answers: CapabilityAnswers


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

    def route_capability(self, state: dict) -> tuple[CapabilityChoiceAnswer, dict]:
        payload = {
            "state": state,
            "model": "kev-latest",
            "questions": {
                "capability": {
                    "type": "choice",
                    "instructions": CAPABILITY_INSTRUCTIONS,
                    "criteria": CAPABILITY_CRITERIA,
                }
            },
        }
        try:
            response = self.client.post(
                get_settings().kev_base_url.rstrip("/") + "/v1/systemone",
                json=payload,
            )
            response.raise_for_status()
            raw = response.json()
            answer = CapabilityKevResponse.model_validate(raw).answers.capability
        except (httpx.HTTPError, ValueError) as exc:
            raise KevUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return answer, raw


@lru_cache(maxsize=1)
def get_kev_provider() -> KevProvider:
    return KevProvider()

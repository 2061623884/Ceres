"""Provider failures become a single, replayable refusal receipt."""
import uuid

import pytest

from app.llm.errors import LLMProviderError
from support import create_session, post_turn


@pytest.mark.parametrize("retryable", [True, False])
def test_provider_error_refuses_and_replays_without_another_model_call(
    client, semantic_provider, retryable
):
    provider = semantic_provider([LLMProviderError("UPSTREAM_FAILURE", "Unavailable", retryable)])
    sid = create_session(client)
    request = {"request_id": str(uuid.uuid4()), "message": "买鸡蛋",
               "expected_task_id": None, "expected_state_version": 0}
    first = post_turn(
        client, sid, request["message"], None, request_id=request["request_id"]
    )
    assert first.status_code == 200, first.json()
    assert first.json()["route"] == "refuse"
    assert first.json()["plan_effect"] == "keep"
    assert any(row.get("code") == "UPSTREAM_FAILURE" for row in first.json()["action_results"])
    replay = post_turn(
        client, sid, request["message"], None, request_id=request["request_id"]
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert len(provider.requests) == 1
    assert client.get("/api/v1/cart").json()["items"] == []

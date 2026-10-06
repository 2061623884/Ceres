"""Answer-stage candidates retain their actual displayed order across turns."""

from __future__ import annotations

import pytest

from app.agent.protocol import CandidateSet, answer_schema, parse_proposal
from app.agent.turn_primitives import TurnSnapshot, build_request
from app.prompts.semantic import PROPOSAL_EXAMPLES
from support import create_session, post_turn
from support.semantic_agent import pick, recommend_then, topic_rows


def test_answer_missing_display_refs_fails_protocol_validation(monkeypatch):
    from app.agent.graph.nodes import answer as answer_node
    from app.agent.protocol import parse_proposal

    monkeypatch.setattr(
        answer_node, "propose_round", lambda *args, **kwargs: ({"reply": "推荐候选。"}, 2)
    )
    state = {
        "session": {}, "authoritative": {}, "candidate": {}, "staged": {}, "result": {},
        "turn": {"parsed_proposal": parse_proposal({"reads": [{"kind": "recommend"}]})},
    }
    result = answer_node._grounded_answer(state, None)
    assert result["turn"]["halt"] == "failed"
    assert result["turn"]["error"]["code"] == "MALFORMED_PROPOSAL"
    assert not result["turn"].get("answer_reply")


def test_build_request_numbers_the_actual_displayed_order():
    displayed = [
        {"ref": "egg-choice", "kind": "dish", "name": "蛋炒饭"},
        {"ref": "green-choice", "kind": "dish", "name": "青椒肉丝"},
    ]
    snapshot = TurnSnapshot(
        turn_mode="active",
        message="就第二个",
        current_plan={
            "groups": [{"ref": "tomato-group", "name": "番茄炒蛋"}],
            "items": [{"name": "新鲜番茄 500克"}, {"name": "鲜鸡蛋 6枚装"}],
        },
        displayed_candidates=displayed,
        recent_messages=[
            {"role": "assistant", "content": "1. 蛋炒饭\n2. 青椒肉丝\n已按条件先配番茄炒蛋。"}
        ],
    )

    request = build_request(snapshot, CandidateSet())

    assert [(row["position"], row["ref"]) for row in request["displayed_candidates"]] == [
        (1, "egg-choice"), (2, "green-choice"),
    ]
    assert "position" not in snapshot.displayed_candidates[0]
    assert request["current_plan"]["groups"][0]["name"] == "番茄炒蛋"


def test_prompt_example_maps_jiu_second_to_the_second_displayed_ref():
    request, raw_proposal = next(example for example in PROPOSAL_EXAMPLES
                                 if example[0]["user_message"] == "就第二个")
    parsed = parse_proposal(raw_proposal)

    assert request["user_message"] == "就第二个"
    assert request["current_plan"]["groups"][0]["name"] == "番茄炒蛋"
    assert [row["position"] for row in request["displayed_candidates"]] == [1, 2]
    assert parsed.understanding.new_goal.target_name == "青椒肉丝"
    assert parsed.mutations[0].candidate_ref == "example_green_choice"


@pytest.mark.parametrize("message,index", [("第二个", 1), ("就第一个", 0)])
def test_recommendation_ordinal_selects_actual_displayed_candidate(
    client, semantic_provider, message, index
):
    shown = []

    def display(request):
        rows = topic_rows(request)
        assert len(rows) >= 3
        # Deliberately change retrieval order and omit one retrieved candidate.
        shown.extend([rows[2], rows[0]])
        return {"reply": "推荐这两道菜。", "display_refs": [row["ref"] for row in shown]}

    def select(request):
        displayed = request["displayed_candidates"]
        assert [row["ref"] for row in displayed] == [row["ref"] for row in shown]
        selected = displayed[index]
        candidate = next(
            row for row in request["candidates"]["dishes"] if row["ref"] == selected["ref"]
        )
        return pick("dish", candidate)

    provider = semantic_provider([*recommend_then(None, display), select])
    session_id = create_session(client)
    first = post_turn(client, session_id, "推荐几个菜")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["plan"] is None and body["plan_effect"] == "keep"
    assert f"1. {shown[0]['name']}\n2. {shown[1]['name']}" in body["message"]
    assert provider.requests[1]["protocol"] == answer_schema()

    second = post_turn(client, session_id, message, body)
    assert second.status_code == 200, second.text
    selected = second.json()
    assert selected["plan_effect"] == "replace", selected
    assert selected["plan"]["targets"][0]["target_id"] == shown[index]["dish_id"]
    assert client.get("/api/v1/cart").json()["items"] == []


def test_answer_unknown_display_ref_is_refused_and_not_saved(client, semantic_provider):
    provider = semantic_provider([
        {"reads": [{"kind": "recommend"}]},
        {"reply": "推荐这个。", "display_refs": ["never-issued"]},
        {"reply": "看看。"},
    ])
    session_id = create_session(client)
    first = post_turn(client, session_id, "推荐几个菜")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["plan"] is None
    assert any(row.get("code") == "UNKNOWN_CANDIDATE_REF" for row in body["action_results"])
    assert "推荐这个。" not in body["message"]

    second = post_turn(client, session_id, "看看", body)
    assert second.status_code == 200, second.text
    assert provider.requests[-1]["displayed_candidates"] == []


def test_ordinal_with_unissued_target_ref_is_refused(client, semantic_provider):
    semantic_provider([
        *recommend_then(None, lambda request: {
            "reply": "推荐第一道。", "display_refs": [topic_rows(request)[0]["ref"]]
        }),
        {"target": {"kind": "meal", "name": "番茄炒蛋", "intent": "buy", "ref": "never-issued"}},
    ])
    session_id = create_session(client)
    first = post_turn(client, session_id, "推荐几个菜").json()
    second = post_turn(client, session_id, "就第一个", first)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["plan"] is None and body["plan_effect"] == "keep"
    assert any(row.get("code") == "UNKNOWN_CANDIDATE_REF" for row in body["action_results"])


@pytest.mark.parametrize("display_refs", [None, "first", [""], ["ref"] * 13])
def test_answer_malformed_display_refs_is_refused(client, semantic_provider, display_refs):
    semantic_provider([
        {"reads": [{"kind": "recommend"}]},
        {"reply": "推荐候选。", "display_refs": display_refs},
    ])
    session_id = create_session(client)
    response = post_turn(client, session_id, "推荐几个菜")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"] is None
    assert any(row.get("code") == "MALFORMED_PROPOSAL" for row in body["action_results"])
    assert "推荐候选。" not in body["message"]

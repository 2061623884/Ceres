"""A shopper can name a dish when asking for their historical plan."""

import pytest

from support import create_session, send_turn
from support.semantic_agent import Continuation, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_named_history_lookup_finds_the_owned_snapshot(indexed_client, semantic_provider, run):
    semantic_provider([request_new("dish", "番茄炒蛋", people=2, mode="self_cook")])
    sid = create_session(indexed_client)
    source = send_turn(indexed_client, sid, "两人份番茄炒蛋")

    def answer(request):
        assert request["query_results"][0]["plans"], request["query_results"][0]
        row = request["query_results"][0]["plans"][0]
        assert row["plan_id"] == source["plan"]["plan_id"]
        return {"reply": f"找到了方案{row['plan_id']}，本次需重新配货。", "display_refs": []}

    semantic_provider([{"reads": [{"kind": "history", "topic": "番茄炒蛋"}]}, Continuation(answer)])
    new_sid = create_session(indexed_client)
    found = send_turn(indexed_client, new_sid, "查我之前的番茄炒蛋方案")
    assert source["plan"]["plan_id"] in found["message"]
    assert found["plan"] is None
    assert indexed_client.get("/api/v1/cart").json()["items"] == []

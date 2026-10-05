"""Memory management uses Guide chat and the existing anonymous owner."""

import pytest

from support import create_session, post_turn, send_turn
from support.semantic_agent import Continuation, request_new
from support.v2_fixture import source_database_path
from test_semantic_phase1_purchase import indexed_client


@pytest.mark.parametrize("run", [1, 2])
def test_explicit_memory_is_listed_in_a_new_session(client, semantic_provider, run):
    semantic_provider([
        {"memory": {"verb": "save", "category": "user", "content": "我平时更喜欢百事可乐"}},
        {"memory": {"verb": "list"}},
    ])
    sid = create_session(client)
    saved = send_turn(client, sid, "请记住我平时更喜欢百事可乐")
    assert saved["answer_status"] == "accepted", saved
    record = next(row for row in saved["action_results"] if row["type"] == "memory")["records"][0]
    assert (record["category"], record["source"], record["expires_at"]) == ("user", "explicit", None)
    other_session = create_session(client)
    listed = send_turn(client, other_session, "你记住了什么？")
    assert record in next(row for row in listed["action_results"] if row["type"] == "memory")["records"]
    assert "百事可乐" in listed["message"]
    assert listed["plan"] is None and client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_four_categories_reopen_update_delete_and_owner_isolation(client, semantic_provider, run):
    from app.core.database import SessionLocal
    from app.services.memory_service import MemoryService

    categories = {"user": "更喜欢百事可乐", "feedback": "每次先告诉我推荐理由",
                  "project": "周五晚饭采购", "reference": "可乐商品 demo:cn-pepsi-original-330ml-can"}
    semantic_provider([{"memory": {"verb": "save", "category": key, "content": value}}
                       for key, value in categories.items()])
    sid = create_session(client)
    previous = None
    records = []
    for key, value in categories.items():
        previous = send_turn(client, sid, f"请长期保存：{value}", previous)
        records.extend(next(row for row in previous["action_results"] if row["type"] == "memory")["records"])
    owner = client.cookies.get("sg_owner_id")
    with SessionLocal() as reopened:
        stored = MemoryService(reopened, owner).list_valid()
        assert {row.category for row in stored} == set(categories)
        assert all(row.source == "explicit" and row.expires_at is None for row in stored)
    target = records[0]
    semantic_provider([
        {"memory": {"verb": "update", "ref": target["ref"], "content": "更喜欢可口可乐"}},
        {"memory": {"verb": "delete", "ref": target["ref"]}},
        {"memory": {"verb": "list"}},
    ])
    sid = create_session(client)
    changed = send_turn(client, sid, "把可乐偏好更正成可口可乐")
    assert "已更正" in changed["message"] and "可口可乐" in changed["message"]
    deleted = send_turn(client, sid, "删除可乐偏好", changed)
    assert "已删除" in deleted["message"]
    listed = send_turn(client, sid, "查询所有记忆", deleted)
    remaining = next(row for row in listed["action_results"] if row["type"] == "memory")["records"]
    assert len(remaining) == 3 and all(row["ref"] != target["ref"] for row in remaining)
    client.cookies.clear()
    semantic_provider([{"memory": {"verb": "list"}}, {"memory": {"verb": "delete", "ref": remaining[0]["ref"]}}])
    stranger_sid = create_session(client)
    empty = send_turn(client, stranger_sid, "查询我的记忆")
    assert next(row for row in empty["action_results"] if row["type"] == "memory")["records"] == []
    refused = post_turn(client, stranger_sid, "删除这条记忆", empty)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "MEMORY_NOT_FOUND"
    with SessionLocal() as reopened:
        assert len(MemoryService(reopened, owner).list_valid()) == 3


@pytest.mark.parametrize("run", [1, 2])
def test_recall_is_bounded_but_explicit_list_is_complete(client, semantic_provider, run):
    def inspect_recall(request):
        assert len(request["memories"]) <= 5
        assert sum(len(row["content"]) for row in request["memories"]) <= 2000
        assert request["requirements"].get("specification", {}) == {}
        return {"memory": {"verb": "list"}}

    semantic_provider([{"memory": {"verb": "save", "category": "user", "content": f"偏好{i}：" + "可乐" * 180}}
                       for i in range(8)] + [inspect_recall])
    sid = create_session(client)
    previous = None
    for i in range(8):
        previous = send_turn(client, sid, f"记住偏好{i}", previous)
    other = create_session(client)
    listed = send_turn(client, other, "请查询所有可乐记忆")
    assert len(next(row for row in listed["action_results"] if row["type"] == "memory")["records"]) == 8


@pytest.mark.parametrize("run", [1, 2])
def test_memory_deletion_preserves_plan_messages_and_temporary_conditions(client, semantic_provider, run):
    semantic_provider([
        {"memory": {"verb": "save", "category": "user", "content": "偏好番茄"}},
        request_new("dish", "番茄炒蛋", people=2, mode="self_cook", constraints={"budget_yuan": 50}),
    ])
    sid = create_session(client)
    saved = send_turn(client, sid, "请记住我喜欢番茄")
    ref = next(row for row in saved["action_results"] if row["type"] == "memory")["records"][0]["ref"]
    prepared = send_turn(client, sid, "今天两个人做番茄炒蛋，预算50元", saved)
    before = client.get(f"/api/v1/guide/sessions/{sid}?include_messages=1").json()
    assert before["plan"] is not None
    semantic_provider([{"memory": {"verb": "delete", "ref": ref}}, {"memory": {"verb": "list"}}])
    deleted = send_turn(client, sid, "删掉番茄偏好", prepared)
    after = client.get(f"/api/v1/guide/sessions/{sid}?include_messages=1").json()
    assert after["plan"] == before["plan"]
    assert all(row in after["messages"] for row in before["messages"])
    listed = send_turn(client, sid, "记住了什么", deleted)
    assert next(row for row in listed["action_results"] if row["type"] == "memory")["records"] == []
    assert client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_current_brand_exception_wins_without_editing_memory(indexed_client, semantic_provider, run):
    def compare(brand):
        def propose(request):
            assert any(row["content"] == "平时喜欢百事可乐" for row in request["memories"])
            assert request["requirements"].get("specification", {}).get("brand") is None
            return {"reads": [{"kind": "compare", "topic": "可乐"}],
                    "constraints": {"specification": {"brand": brand}}}
        return propose

    def answer(request):
        rows = request["query_results"][0]["sellable_products"]
        return {"reply": "按本次条件查询当前报价。", "display_refs": [row["ref"] for row in rows]}

    semantic_provider([
        {"memory": {"verb": "save", "category": "user", "content": "平时喜欢百事可乐"}},
        compare("可口可乐"), Continuation(answer), compare("百事可乐"), Continuation(answer),
        {"memory": {"verb": "list"}},
    ])
    sid = create_session(indexed_client)
    send_turn(indexed_client, sid, "请记住平时喜欢百事可乐")
    today = create_session(indexed_client)
    exception = send_turn(indexed_client, today, "今天例外，只比较可口可乐")
    assert exception["product_cards"] and all(row["brand"] == "可口可乐" for row in exception["product_cards"])
    normal = create_session(indexed_client)
    remembered = send_turn(indexed_client, normal, "按我平时的偏好比较可乐")
    assert len(remembered["product_cards"]) == 1 and remembered["product_cards"][0]["brand"] == "百事可乐"
    listed = send_turn(indexed_client, normal, "查询记忆", remembered)
    assert [row["content"] for row in next(row for row in listed["action_results"] if row["type"] == "memory")["records"]] == ["平时喜欢百事可乐"]

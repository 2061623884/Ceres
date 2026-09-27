"""The resolved turn context: what the one chain is given, and from where.

This file used to hold pure unit tests for the retired routing modules
(``TurnInterpreter`` / ``DecisionPolicy`` / ``AnswerGenerator``). Their subject
no longer exists, so they are retired rather than rewritten — the routing they
described is now covered end to end by ``test_semantic_only_architecture.py``.

What survives is the part that is still real: the resolver that assembles the
context every turn is handed. The retired pipeline tests are not part of this suite.
"""

from __future__ import annotations

import json

from app.agent.clarification_state import PendingClarification
from app.models.session import GuideSession, GuideTask
from app.services.conversation_service import ConversationService


def test_context_resolver_includes_messages_pending_and_purchase(db_session):
    owner_id = "owner-test"
    session = GuideSession(
        session_id="sess-resolver",
        owner_id=owner_id,
        entry_context_json=json.dumps({"store_id": "store-demo-01"}),
    )
    task = GuideTask(
        task_id="task-resolver",
        session_id="sess-resolver",
        owner_id=owner_id,
        intent="purchase_task",
        status="completed",
        requirements_json=json.dumps({"goal": "番茄炒蛋", "people": 2}),
        cart_result_json=json.dumps(
            {
                "items_added": [{"sku_id": "sku-egg", "name": "鸡蛋", "quantity": 2, "line_total_fen": 1200}],
                "total_fen": 1200,
                "cart_version": 3,
            }
        ),
        pending_clarification_json=PendingClarification(
            question_id="people",
            question="几个人？",
            slot="people",
        ).to_json(),
    )
    db_session.add(session)
    db_session.add(task)
    db_session.flush()
    session.current_task_id = task.task_id

    conv = ConversationService(db_session, owner_id)
    conv.save_message(
        "sess-resolver",
        task_id=task.task_id,
        role="user",
        kind="text",
        content="我想吃番茄炒蛋",
    )
    conv.save_message(
        "sess-resolver",
        task_id=task.task_id,
        role="assistant",
        kind="text",
        content="已整理购买清单",
    )
    db_session.commit()

    from app.agent.context_resolver import ContextResolver

    resolved = ContextResolver(db_session, owner_id).resolve("sess-resolver")
    assert len(resolved.recent_messages) >= 2
    assert resolved.pending_clarification is not None
    assert resolved.pending_clarification.slot == "people"
    assert resolved.purchase_summary is not None
    assert resolved.purchase_summary["items"][0]["name"] == "鸡蛋"

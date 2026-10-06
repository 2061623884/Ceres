"""The category page is context, not a second pipeline.

The retired chain gave a category page its own task type and its own
requirement-parser LLM call. Both are gone: a category entry now runs the same
turn as every other page — real retrieval, a model proposal, the executor and
the business services.

These tests cover the three things that could still go wrong on that page:

* a common product name uses real lookup order on the category page;
* a plan built from it is a normal pending plan that writes nothing to the cart;
* a task row that still carries the retired ``category_selection`` intent (a
  pre-cutover row) runs the same chain as any other task.
"""

from __future__ import annotations

import json
import uuid

from support import create_session, post_turn
from support.semantic_agent import lookup_then_add
from test_semantic_phase1_purchase import indexed_client  # noqa: F401

BAKING = {"page": "category", "category_id": "baking"}


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


def _db(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def test_the_category_page_uses_real_common_product_lookup_without_cart_write(
    indexed_client, semantic_provider
):
    """Common product names may bind a real hit; planning still cannot buy."""
    client = indexed_client
    semantic_provider(
        [
            {
                "target": {"kind": "product", "name": "面粉", "intent": "buy"},
                "constraints": {"budget_yuan": 20, "specification": {"size": "small"}},
                "lookups": [{"kind": "product", "query": "面粉"}],
            }
        ]
    )
    sid = create_session(client, page="category", category_id="baking")
    body = turn(client, sid, "想做蛋糕，面粉小包装，20元以内").json()

    assert body["plan"] and body["plan_effect"] == "replace", body
    lookup = next(row for row in body["action_results"] if row["kind"] == "lookup")
    assert lookup["status"] == "completed" and lookup["retrieval_status"] == "ok", lookup
    line = body["plan"]["items"][0]
    assert line["sku_id"] == "demo:cake-flour-250g", line
    assert line["unit_price_fen"] == 680 and line["evidence"]["stock_verified"], line
    assert body["plan"]["selected_total_fen"] <= 2000, body
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_category_turn_can_plan_a_real_product_but_writes_no_cart(
    indexed_client, semantic_provider
):
    # An exact name and a common product name both use the same purchase chain.
    client = indexed_client
    semantic_provider(lookup_then_add("product", "低筋面粉 250克（小包装）"))
    sid = create_session(client, page="category", category_id="baking")
    body = turn(client, sid, "帮我配齐做蛋糕的材料").json()

    assert body["plan"], body
    target = body["plan"]["targets"][0]
    assert target["kind"] == "product", target
    assert body["task_id"]
    # The retrieval really happened and really returned a sellable row: the
    # built plan's own line carries the real SKU, price and stock evidence, and
    # the turn's lookup receipt reports a completed retrieval (there is no
    # second model call to inspect query_results on — spec rule 1, one pass).
    lookup_receipt = next(
        r for r in body["action_results"] if r.get("kind") == "lookup"
    )
    assert lookup_receipt["status"] == "completed", lookup_receipt
    assert lookup_receipt["retrieval_status"] == "ok", lookup_receipt
    line = body["plan"]["items"][0]
    assert line["sku_id"] and line["evidence"]["stock_verified"], line
    assert client.get("/api/v1/cart").json()["items"] == [], "a plan is not a purchase"


def test_an_existing_category_selection_task_runs_the_same_chain(
    client, semantic_provider
):
    """A pre-cutover task row is not a reason to take a different route."""
    from app.models.session import GuideSession, GuideTask

    sid = create_session(client, page="category", category_id="baking")
    db = _db(client)
    try:
        session = db.get(GuideSession, sid)
        task = GuideTask(
            task_id="task-legacy-category",
            session_id=sid,
            owner_id=session.owner_id,
            state_version=1,
            #: The retired intent, as an old row would still carry it.
            intent="category_selection",
            current_step="understanding",
            status="active",
            user_confirmed=False,
            requirements_json=json.dumps({"category_id": "baking"}),
        )
        db.add(task)
        session.current_task_id = task.task_id
        db.commit()
    finally:
        db.close()

    semantic_provider(lookup_then_add("product", "低筋面粉 250克（小包装）"))
    resp = turn(
        client,
        sid,
        "帮我选蛋糕面粉",
        {"task_id": "task-legacy-category", "state_version": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"] == "task-legacy-category"
    assert body["plan"], body
    assert client.get("/api/v1/cart").json()["items"] == []

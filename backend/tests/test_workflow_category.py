"""The category page is context, not a second pipeline.

The retired chain gave a category page its own task type and its own
requirement-parser LLM call. Both are gone: a category entry now runs the same
turn as every other page — real retrieval, a model proposal, the executor and
the business services.

These tests cover the three things that could still go wrong on that page:

* the retrieval is a real **product** lookup for the category the shopper is
  browsing, and the model asks before planning anything;
* a plan built from it is a normal pending plan that writes nothing to the cart;
* a task row that still carries the retired ``category_selection`` intent (a
  pre-cutover row) runs the same chain as any other task.
"""

from __future__ import annotations

import json
import uuid

from support import create_session, post_turn
from support.semantic_agent import (
    Continuation,
    lookup_matches,
    lookup_then_add,
)

BAKING = {"page": "category", "category_id": "baking"}


def turn(client, session_id: str, message: str, previous: dict | None = None):
    previous = previous or {}
    return post_turn(client, session_id, message, previous, request_id=str(uuid.uuid4()))


def _db(client):
    from app.core import database as db_module

    return db_module.SessionLocal()


def test_the_category_page_retrieves_real_products_then_asks(
    client, semantic_provider
):
    """A real product lookup on the browsed category, and a question from it."""

    def ask(request):
        rows = lookup_matches(request, "product")
        assert rows, "the baking category must retrieve real products"
        return {
            "uncertainties": [
                {
                    "slot": "product_choice",
                    "question": "这几种面粉你要哪一种？",
                    "options": [{"candidate_ref": r["ref"]} for r in rows[:3]],
                }
            ]
        }

    semantic_provider(
        [{"lookups": [{"kind": "product", "query": "面粉"}]}, Continuation(ask)]
    )
    sid = create_session(client, page="category", category_id="baking")
    body = turn(client, sid, "想做蛋糕，面粉小包装，20元以内").json()

    assert body["plan"] is None, "a question is not a plan"
    assert body["plan_effect"] == "keep"
    pending = body["pending_clarifications"]
    assert pending and pending[0]["options"], body
    assert all(o.get("label") for o in pending[0]["options"]), pending
    assert client.get("/api/v1/cart").json()["items"] == []


def test_a_category_turn_can_plan_a_real_product_but_writes_no_cart(
    client, semantic_provider
):
    provider = semantic_provider(lookup_then_add("product", "面粉", "面粉"))
    sid = create_session(client, page="category", category_id="baking")
    body = turn(client, sid, "帮我配齐做蛋糕的材料").json()

    assert body["plan"], body
    target = body["plan"]["targets"][0]
    assert target["kind"] == "product", target
    assert body["task_id"]
    # The retrieval really happened and really returned sellable rows.
    product_results = [
        r
        for r in provider.requests[-1]["query_results"]
        if r.get("lookup_kind") == "product"
    ]
    assert product_results and product_results[0]["matches"], product_results
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

    semantic_provider(lookup_then_add("product", "面粉", "面粉"))
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

"""The Graph commit coordinator: one transaction, one complete receipt.

This is the only place a Guide turn writes business authority. It runs inside the
``respond`` node and owns the transaction:

* a fresh, authoritative guard runs here against the **stage-recorded expected**
  preconditions (never a freshly read value), with no-op conditional UPDATEs as
  the write lock;
* the business effect (a batch applied in order), the user/assistant messages,
  the plan snapshot and the receipt are written in the same transaction;
* the receipt row is finalized by ``TurnReceiptService.complete`` (flush only,
  with its own fencing CAS); the coordinator's single ``db.commit()`` is the only
  commit boundary.

Any failure rolls the whole turn back; the coordinator then records the real
failure on the request receipt in a separate transaction, so a later request with
the same id replays that error instead of re-executing. ``respond`` is the only
node that writes business authority.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.agent import context as turn_context
from app.agent.graph.response_contract import build_graph_response, prepare_graph_message
from app.agent.graph.runtime import TurnRuntime
from app.agent.protocol import SemanticProtocolError
from app.agent.turn_primitives import TIMEOUT_CODE
from app.agent.state import TaskState
from app.core.errors import AppError
from app.models.session import GuideSession, GuideTask
from app.services.conversation_service import ConversationService
from app.services.plan_commit_service import PlanCommitService
from app.services.task_lifecycle_service import TaskLifecycleService, TurnAnchor


def _deny(code: str, message: str) -> dict[str, Any]:
    return {"allowed": False, "code": code, "message": message}


def final_guard(
    db: Any,
    runtime: TurnRuntime,
    staged: dict[str, Any],
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """The authoritative guard, re-run *inside* the commit transaction.

    It re-reads the live owner/anchor/versions, compares them against the
    **stage-recorded expected** preconditions (never a freshly read value), and
    takes the write lock with no-op conditional UPDATEs so the expected versions
    cannot move under us. A denied verdict returns a refusal; the caller then
    writes only the receipt.
    """
    pre = staged.get("preconditions") or {}
    if runtime.db is None:
        raise ValueError("DB_REQUIRED: the runtime context must carry a database session")

    live = db.execute(
        text(
            "SELECT session_version, current_task_id FROM guide_sessions "
            "WHERE session_id = :sid AND owner_id = :oid"
        ),
        {"sid": pre.get("session_id") or runtime.session_id, "oid": runtime.owner_id},
    ).first()
    if live is None:
        return _deny("SESSION_FORBIDDEN", "Session not found")
    if int(live[0] or 0) != int(pre.get("session_version") or 0):
        return _deny("STALE_STATE", "会话版本已变化，本轮改动未执行。")
    if live[1] != pre.get("task_id"):
        return _deny("STALE_STATE", "回合开始后会话的任务已变化，本轮改动未执行。")

    # The immutable server entry anchor is what the final check defends: a task
    # appearing or becoming terminal between the request precheck and now cannot
    # move it, whatever the session version says.
    entry = getattr(runtime, "entry_anchor", None) or pre
    if int(live[0] or 0) != int(entry.get("session_version") or 0):
        return _deny("STALE_STATE", "会话版本已变化，本轮改动未执行。")
    if live[1] != entry.get("task_id"):
        return _deny("STALE_STATE", "回合开始后会话的任务已变化，本轮改动未执行。")
    if entry.get("task_id"):
        live_task_version = db.execute(
            text(
                "SELECT state_version FROM guide_tasks "
                "WHERE task_id = :tid AND owner_id = :oid"
            ),
            {"tid": entry.get("task_id"), "oid": runtime.owner_id},
        ).scalar_one_or_none()
        if live_task_version is None or int(live_task_version) != int(
            entry.get("state_version") or 0
        ):
            return _deny("STALE_STATE", "清单已被其他操作修改，本轮改动未执行。")

    anchor = TurnAnchor(
        session_id=pre.get("session_id") or runtime.session_id,
        task_id=pre.get("task_id"),
        state_version=int(pre.get("state_version") or 0),
    )
    try:
        TaskLifecycleService(db, runtime.owner_id).assert_turn_anchor(anchor)
    except AppError as exc:
        return _deny(exc.detail["error"]["code"], exc.detail["error"]["message"])

    # Acquire the write lock and pin the *original* expected versions: a no-op
    # conditional UPDATE succeeds only if nothing moved since the stage.
    locked = db.execute(
        text(
            "UPDATE guide_sessions SET session_version = session_version "
            "WHERE session_id = :sid AND owner_id = :oid AND session_version = :ver "
            "AND ((current_task_id IS NULL AND :anchor IS NULL) OR current_task_id = :anchor)"
        ),
        {
            "sid": pre.get("session_id") or runtime.session_id,
            "oid": runtime.owner_id,
            "ver": int(pre.get("session_version") or 0),
            "anchor": pre.get("task_id"),
        },
    )
    if locked.rowcount != 1:
        return _deny("STALE_STATE", "会话版本已变化，本轮改动未执行。")
    if pre.get("task_id"):
        locked_task = db.execute(
            text(
                "UPDATE guide_tasks SET state_version = state_version "
                "WHERE task_id = :tid AND owner_id = :oid AND state_version = :ver"
            ),
            {
                "tid": pre.get("task_id"),
                "oid": runtime.owner_id,
                "ver": int(pre.get("state_version") or 0),
            },
        )
        if locked_task.rowcount != 1:
            return _deny("STALE_STATE", "清单已被其他操作修改，本轮改动未执行。")

    if staged.get("kind") == "mutation":
        if not decision or decision.get("route") != "mutation" or decision.get("write_blocked"):
            return _deny("WRITE_BLOCKED", "本轮未获得写入授权，清单没有改动。")
    if runtime.stop():
        return _deny("STOPPED", "已停止，尚未执行的修改没有写入。")
    if runtime.expired():
        return _deny(TIMEOUT_CODE, "本轮处理超时，未执行的修改没有写入。")
    return {"allowed": True, "code": None, "message": None}


def _task_state(db: Any, session: GuideSession) -> TaskState | None:
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    if task is None:
        return None
    return TaskState.from_db(task, entry_context={})


def _refuse_unwritable(runtime: TurnRuntime) -> None:
    if runtime.stop():
        raise SemanticProtocolError("STOPPED", "已停止，尚未执行的修改没有写入。")
    if runtime.expired():
        from app.agent.turn_primitives import TIMEOUT_CODE

        raise SemanticProtocolError(TIMEOUT_CODE, "本轮处理超时，未执行的修改没有写入。")


def commit_graph_turn(state: dict[str, Any], runtime: TurnRuntime) -> dict[str, Any]:
    """Apply the staged effect and persist the fixed receipt, in one transaction."""
    db = runtime.db
    if db is None:
        raise ValueError("DB_REQUIRED: the runtime context must carry a database session")
    staged = state["staged"]

    session = db.get(GuideSession, runtime.session_id)
    if session is None or session.owner_id != runtime.owner_id:
        raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

    reservation = runtime.reservation
    receipts = runtime.receipt_service
    conversation = ConversationService(db, runtime.owner_id)
    try:
        # The request's view context is persisted inside this same business
        # transaction — never as a pre-admission session write (which would hold a
        # write lock while the request is admitted). A replayed request without a
        # new view context keeps the stored one.
        if runtime.view_context is not None:
            session.view_context_json = json.dumps(runtime.view_context)
        # Everything from here is inside the transaction boundary: the final
        # guard takes the write lock and assert_owned can fail on a lost lease —
        # either must roll back before the coordinator releases the reservation.
        guard = final_guard(db, runtime, staged, state["turn"].get("decision"))
        allowed = bool(guard.get("allowed"))
        if reservation is not None and receipts is not None:
            receipts.assert_owned(db, reservation)
        user_msg = conversation.save_message(
            runtime.session_id,
            task_id=session.current_task_id,
            role="user",
            kind="text",
            content=state["turn"]["user_input"],
            request_id=runtime.request_id,
        )

        plan: dict[str, Any] | None = None
        committed = False
        action_results: list[dict[str, Any]] = []
        if allowed and staged.get("kind") == "mutation":
            plan, action_results = _apply_batch(db, runtime, session, staged)
            committed = any(row.get("saved") for row in action_results)

        context_plan = dict(staged.get("context_plan") or {})
        previous_task_id = (staged.get("preconditions") or {}).get("task_id")
        if (
            committed
            and context_plan
            and previous_task_id
            and session.current_task_id != previous_task_id
        ):
            # Preparation precedes the commit, so only the committed result can
            # tell whether a terminal task was replaced. Its old questions and
            # displayed refs belong to the previous task, not the new one.
            context_plan.update(
                pending=list(context_plan.get("new_pending") or []),
                task_switched=True,
                clear_goal_candidate=True,
                changed=True,
            )
            candidate = context_plan.get("candidate_to_store")
            if candidate is not None:
                current = _task_state(db, session)
                context_plan["candidate_to_store"] = {
                    **candidate,
                    "task_id": session.current_task_id,
                    "plan_version": current.state_version if current else None,
                }
        has_plan_pending = "pending" in context_plan
        new_pending = list(context_plan.get("new_pending") or staged.get("pending") or [])
        # An intentionally emptied list is a real value: only fall back to the
        # staged questions when the context plan carries no pending key at all.
        merged_pending = (
            list(context_plan["pending"])
            if has_plan_pending
            else list(staged.get("pending") or [])
        )
        displayed = list(context_plan.get("displayed") or [])
        if allowed and context_plan:
            _apply_context(db, runtime, session, staged, context_plan)
            session = db.get(GuideSession, runtime.session_id)
        if allowed and not has_plan_pending:
            # No context plan was applied this turn: the response must report the
            # pending questions that are really stored, not an invented empty list.
            merged_pending = turn_context.pending_for_session(db, session)

        proposal = state["turn"].get("parsed_proposal")
        if allowed and proposal is not None:
            _persist_session_constraints(db, runtime, session, proposal)
        effect = "replace" if plan else "keep"
        refusal_message = None
        if not allowed:
            # A guard denial publishes no un-persisted question as if it were real,
            # and must not claim the stored pending questions were cleared: the
            # response reports the real stored state, which this turn never wrote.
            new_pending = []
            merged_pending = turn_context.pending_for_session(db, session)
            # A turn that already carries its own server-authored reason
            # (``refuse_prepare`` for a stop/timeout/blocked write) keeps that
            # reason; the final guard only supplies its wording when the stage
            # itself did not refuse. Replacing the staged reason would relabel a
            # stop as a generic guard denial.
            staged_error = staged.get("error") or {}
            if staged_error.get("understanding"):
                refusal_message = understanding_wrapper(staged_error)
                action_results = [understanding_row(staged_error)]
            else:
                # A turn that already carries its own server-authored reason
                # (``refuse_prepare`` for a stop/timeout/blocked write) keeps that
                # reason; the final guard only supplies its wording when the stage
                # itself did not refuse. Replacing the staged reason would relabel a
                # stop as a generic guard denial.
                refusal_message = str(
                    staged_error.get("message")
                    or guard.get("message")
                    or "本轮没有执行修改。"
                )
                action_results = [
                    {
                        "type": "mutation_refused" if staged.get("kind") == "mutation" else "refused",
                        "status": "blocked",
                        "saved": False,
                        "reply_ok": False,
                        "code": staged_error.get("code") or guard.get("code") or "WRITE_BLOCKED",
                        "message": refusal_message,
                    }
                ]
        elif staged.get("error"):
            error = staged["error"]
            if error.get("understanding"):
                refusal_message = understanding_wrapper(error)
                action_results = [understanding_row(error)]
            elif error.get("conflict"):
                # A contradictory/mixed batch is asked about, never half-done:
                # the receipt is a blocked row, exactly as the loop entry writes.
                refusal_message = str(error.get("message") or "本轮没有执行修改。")
                action_results = [
                    {
                        "type": "mutation_refused",
                        "status": "blocked",
                        "saved": False,
                        "reply_ok": True,
                        "code": error.get("code"),
                        "message": refusal_message,
                    }
                ]
            else:
                refusal_message = str(error.get("message") or "这个修改没有执行。")
                # The loop entry's whole-batch refusal wording: name what did not
                # run, then state that the existing plan is unchanged. The batch
                # is refused whole (a later step's business failure rejects it),
                # so nothing was half-applied.
                refusal_message = f"这一步没有完成：{refusal_message} 原来的清单没有变化。"
                action_results = [
                    {
                        "type": "mutation",
                        "status": "failed",
                        "saved": False,
                        "reply_ok": False,
                        "code": error.get("code"),
                        "message": refusal_message,
                    }
                ]
            plan = None
            committed = False

        if allowed and staged.get("kind") == "clarify":
            # Every question this turn really staged is a persisted effect and is
            # receipted as one, with its own slot, exactly as the shared context
            # plan committed it. This mirrors the legacy receipt contract instead
            # of dropping the only effect a clarification turn has.
            for item in new_pending:
                action_results.append(
                    {
                        "type": "clarification",
                        "slot": item.get("slot"),
                        "status": "needs_clarification",
                        "saved": True,
                        "reply_ok": True,
                    }
                )

        read_results = list(state["turn"].get("read_results") or [])
        if read_results and staged.get("kind") in ("mutation", "answer"):
            # Read-only work already performed this turn. It is reported as
            # completed with ``saved=False`` so the client can see what the server
            # fetched without reading it as a write. Legacy put these rows first;
            # the same order is kept so the receipt stays comparable.
            read_rows = [
                {
                    "type": "read_only",
                    "kind": result.get("kind"),
                    "status": result.get("status", "completed"),
                    "saved": False,
                    "reply_ok": True,
                    **{
                        key: result[key]
                        for key in (
                            "retrieval_status",
                            "retrieval_mode",
                            "fallback_reason",
                            "index_version",
                            "code",
                        )
                        if key in result
                    },
                }
                for result in read_results
            ]
            action_results = [*read_rows, *action_results]

        model_reply = str(state["turn"].get("answer_reply") or (proposal.reply if proposal else "") or "")
        if staged.get("kind") == "clarify":
            # Clarification speaks from server-staged questions, not from a
            # Proposal reply that might claim a write which never happened.
            model_reply = ""
        # The answer node already organized this turn's reply from the staged
        # business result. A committed plan's own summary is a post-merge fact,
        # so it is appended here from the plan that was really persisted.
        base_message = str(staged.get("message") or "") if allowed else ""
        if base_message:
            message = base_message
            plan_block = ""
            if plan is not None and effect == "replace":
                plan_block = prepare_graph_message(
                    kind="mutation",
                    model_reply="",
                    plan=plan,
                    plan_effect="replace",
                    action_results=[],
                    pending=[],
                    displayed=[],
                    refusal_message=None,
                )
            if plan_block:
                message = f"{message}\n{plan_block}" if message else plan_block
        else:
            message = prepare_graph_message(
                kind=str(staged.get("kind") or "answer"),
                model_reply=model_reply,
                plan=plan,
                plan_effect=effect,
                action_results=action_results,
                pending=new_pending,
                displayed=displayed,
                refusal_message=refusal_message,
            )
        failed_rows = [row for row in action_results if row.get("status") == "failed"]
        committed_rows = [row for row in action_results if row.get("status") == "committed"]
        if failed_rows and committed_rows:
            # A partial success is reported as a partial success: what did not run
            # is named first, what really was saved is named second, and the plan
            # is still delivered. The model's own prose is never reused here.
            def _detail(row: dict[str, Any]) -> str:
                return str(row.get("message") or row.get("code") or "操作未完成")

            lead = (
                "这一步没有完成："
                + "；".join(_detail(row) for row in failed_rows)
                + " 已经保存的部分："
                + "；".join(_detail(row) for row in committed_rows)
            )
            message = f"{lead}\n{message}" if message else lead
        if not str(message or "").strip():
            # Nothing was said and nothing was asked. That is a failure, never a
            # success with an empty message (the same rule the loop entry uses).
            if action_results:
                action_results.append(
                    {
                        "type": "understanding_failed",
                        "status": "failed",
                        "saved": False,
                        "reply_ok": False,
                        "code": "NO_REPLY",
                        "message": "模型只给出了动作，没有给出要回答用户的话。",
                        "retryable": False,
                    }
                )
                message = (
                    "这一步没有完成：模型只给出了动作，没有给出要回答用户的话。 "
                    "原来的清单没有变化。"
                )
            else:
                empty_error = {
                    "code": "EMPTY_PROPOSAL",
                    "message": "模型没有给出任何可执行内容",
                    "retryable": True,
                }
                action_results = [understanding_row(empty_error)]
                message = understanding_wrapper(empty_error)
        assistant = conversation.save_message(
            runtime.session_id,
            task_id=session.current_task_id,
            role="assistant",
            kind="plan_ref" if plan else "text",
            content=message,
            request_id=runtime.request_id,
            plan_id=plan.get("plan_id") if plan else None,
            plan_version=plan.get("plan_version") if plan else None,
        )
        if plan:
            conversation.save_plan_snapshot(
                runtime.session_id,
                session.current_task_id,
                plan,
                {"store_id": runtime.store_id, "delivery_zone_id": runtime.delivery_zone_id},
            )

        task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
        response = build_graph_response(
            _task_state(db, session),
            session,
            task,
            runtime,
            state,
            {**staged, "pending": merged_pending},
            guard,
            user_msg=user_msg,
            assistant=assistant,
            plan=plan,
            message=message,
            committed=committed,
            allowed=allowed,
            action_results=action_results,
        )
        if reservation is not None and receipts is not None:
            receipts.complete(db, reservation, response)
        db.commit()
    except Exception:
        db.rollback()
        raise
    _emit_transport_events(runtime, state, staged, plan, effect, allowed, new_pending, message, response)
    return response


def _emit_transport_events(
    runtime: TurnRuntime,
    state: dict[str, Any],
    staged: dict[str, Any],
    plan: dict[str, Any] | None,
    effect: str,
    allowed: bool,
    new_pending: list[dict[str, Any]],
    message: str = "",
    response: dict[str, Any] | None = None,
) -> None:
    """Publish SSE transport events after the business transaction commits.

    Everything here comes from the values this transaction already fixed — the
    committed plan and the built response — so no session/task row is re-read
    and the event can never describe a different version than the receipt.
    """
    sink = getattr(runtime, "progress_sink", None)
    if sink is None:
        return
    if allowed and staged.get("kind") == "clarify":
        for item in new_pending:
            sink.on_clarification(item)
    if allowed and plan and effect != "keep":
        from types import SimpleNamespace

        from app.agent.responses import plan_ready_payload

        fixed = response or {}
        payload = plan_ready_payload(
            SimpleNamespace(
                plan=plan,
                task_id=fixed.get("task_id"),
                state_version=fixed.get("state_version"),
            ),
            SimpleNamespace(session_version=fixed.get("session_version")),
        )
        payload["plan_effect"] = effect
        sink.on_plan_ready(payload)
    # The answer text the model never authored: the receipt's own composed reply.
    # Only a transport that renders deltas asks for them (``answer.delta``), and
    # the full saved text is only ever sent after the commit above.
    wants = getattr(sink, "wants_answer_deltas", None)
    if message and callable(wants) and wants():
        sink.on_answer_delta(message, final=True)


def _apply_batch(
    db: Any, runtime: TurnRuntime, session: GuideSession, staged: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Apply every prepared step, in order, inside this transaction.

    Validation progress is emitted before the final guard. Budget and stop are
    checked again at each write boundary. An exception propagates to the caller's
    rollback: no applied prefix is durable until the whole business/receipt
    transaction commits.
    """
    steps = list(staged.get("batch") or [staged])
    pre = staged.get("preconditions") or {}
    anchor = TurnAnchor(
        session_id=runtime.session_id,
        task_id=pre.get("task_id"),
        state_version=int(pre.get("state_version") or 0),
    )
    plan: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    for step in steps:
        _refuse_unwritable(runtime)
        if step.get("verb") == "add":
            target = PlanCommitService(db, runtime.owner_id).apply_result(
                session,
                _task_state(db, session),
                step["plan_result"],
                step.get("args") or {},
                store_id=runtime.store_id,
                delivery_zone_id=runtime.delivery_zone_id,
                anchor=anchor,
                before_persist=lambda: _refuse_unwritable(runtime),
                opens_new_task=bool(step.get("switching")),
            )
            session = db.get(GuideSession, runtime.session_id)
            task = db.get(GuideTask, target.task_id) if target else None
            plan = json.loads(task.plan_json) if task and task.plan_json else None
            anchor.advance(target.state_version, target.task_id)
        else:
            state = _task_state(db, session)
            if state is None:
                raise SemanticProtocolError("NOTHING_TO_CHANGE", "当前没有可修改的方案")
            state.plan = step.get("plan_patch")
            state.state_version = int(state.state_version or 0) + 1
            state.to_db(
                db,
                expected_version=anchor.state_version if anchor is not None else None,
            )
            anchor.advance(state.state_version, state.task_id)
            plan = dict(state.plan or {})
        results.append(committed_step_row(step))
    return plan, results


def _stated_constraints(proposal: Any) -> dict[str, Any]:
    """The durable user facts this request stated on its read requests."""
    excluded: list[str] = []
    budget: int | None = None
    for item in [*proposal.lookups, *proposal.queries]:
        excluded.extend(getattr(item, "excluded_ingredients", []) or [])
        stated_budget = getattr(item, "budget_fen", None)
        if stated_budget is not None:
            budget = stated_budget if budget is None else min(budget, stated_budget)
    result: dict[str, Any] = {}
    unique = [name for name in dict.fromkeys(str(x) for x in excluded) if name.strip()]
    if unique:
        result["excluded_ingredients"] = unique
    if budget is not None:
        result["budget_fen"] = budget
    return result


def _persist_session_constraints(
    db: Any, runtime: TurnRuntime, session: GuideSession, proposal: Any
) -> None:
    """Save user-stated read constraints as durable session facts.

    A taskless query that states an exclusion ("推荐几个菜，不要花生") must not
    survive only as a recent message: the next request has to honour it. It is
    stored in the existing ``GuideSemanticContext`` (union of exclusions, the
    stricter budget), inside this same transaction, never in a new store.
    """
    stated = _stated_constraints(proposal)
    if not stated:
        return
    context = turn_context.load_context(db, session) or {}
    existing = dict(context.get("session_constraints") or {})
    merged = dict(existing)
    exclusions = list(
        dict.fromkeys(
            [
                *(existing.get("excluded_ingredients") or []),
                *(stated.get("excluded_ingredients") or []),
            ]
        )
    )
    if exclusions:
        merged["excluded_ingredients"] = exclusions
    budgets = [
        value
        for value in (existing.get("budget_fen"), stated.get("budget_fen"))
        if value is not None
    ]
    if budgets:
        merged["budget_fen"] = min(budgets)
    if merged == existing and "session_constraints" in context:
        return
    expected = int(session.session_version or 0)
    cas = db.execute(
        text(
            "UPDATE guide_sessions SET session_version = session_version + 1 "
            "WHERE session_id = :sid AND owner_id = :oid AND session_version = :ver"
        ),
        {"sid": runtime.session_id, "oid": runtime.owner_id, "ver": expected},
    )
    if cas.rowcount != 1:
        raise AppError(409, "STALE_STATE", "会话版本已变化，本轮改动未执行。")
    db.expire(session, ["session_version"])
    turn_context.save_context(db, session, {**context, "session_constraints": merged})


def committed_step_row(step: dict[str, Any]) -> dict[str, Any]:
    """One committed step as its receipt row.

    The row keeps the business identity the step really carries: ``candidate_ref``
    for an add, ``sku_id``/``quantity`` for a row edit. Optional keys with no value
    are omitted rather than emitted as ``null``, so the receipt matches the loop
    entry's shape without dropping any field that has a value.
    """
    row: dict[str, Any] = {
        "type": "mutation",
        "verb": step.get("verb"),
        "group_id": step.get("group_id"),
        "status": "committed",
        "saved": True,
        "reply_ok": True,
        "plan_effect": "replace",
        "message": step.get("message"),
    }
    candidate_ref = step.get("candidate_ref") or (
        (step.get("plan_result") or {}).get("target") or {}
    ).get("ref")
    if candidate_ref:
        row["candidate_ref"] = candidate_ref
    for key in ("sku_id", "quantity"):
        if step.get(key) is not None:
            row[key] = step[key]
    return row


def understanding_wrapper(error: dict[str, Any]) -> str:
    """The loop entry's own wording for a turn it could not understand."""
    if error.get("code") == "MODEL_TIMEOUT":
        return "抱歉，这次响应超时了，请稍后重试。"
    return (
        f"抱歉，这一轮我没能理解清楚（{error.get('code')}）：{error.get('message') or ''} "
        "请换个说法，或直接说想吃什么、想买什么。"
    )


def understanding_row(error: dict[str, Any]) -> dict[str, Any]:
    """An ``understanding_failed`` receipt for a parse/understanding failure.

    Same shape as the loop entry's ``_protocol_error_response``: the turn failed
    before any business effect, so nothing is ``saved`` and the code is the
    protocol error itself.
    """
    return {
        "type": "understanding_failed",
        "status": "failed",
        "saved": False,
        "reply_ok": False,
        "code": error.get("code"),
        "message": error.get("message"),
        "retryable": bool(error.get("retryable")),
    }


def _apply_context(
    db: Any, runtime: TurnRuntime, session: GuideSession, staged: dict[str, Any], plan: dict[str, Any]
) -> None:
    from app.agent.turn_context_plan import ContextPlan, apply_context_plan

    context_model = ContextPlan(**plan)
    db.flush()
    # The final guard pinned the stage expected value; any change since then is
    # this same transaction's own effect, so the CAS rides the current in-tx value.
    expected_sv = int(session.session_version or 0)
    context_now = turn_context.load_context(db, session) or {}
    if context_model.changed:
        cas = db.execute(
            text(
                "UPDATE guide_sessions SET session_version = session_version + 1 "
                "WHERE session_id = :sid AND owner_id = :oid AND session_version = :ver"
            ),
            {"sid": runtime.session_id, "oid": runtime.owner_id, "ver": expected_sv},
        )
        if cas.rowcount != 1:
            raise AppError(409, "STALE_STATE", "会话版本已变化，本轮改动未执行。")
        db.expire(session, ["session_version"])
    apply_context_plan(
        db=db,
        session=session,
        context=context_now,
        plan=context_model,
        session_version_already_bumped=context_model.changed,
    )


__all__ = ["commit_graph_turn", "committed_step_row", "understanding_row", "understanding_wrapper"]

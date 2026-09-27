# Guide request-level LangGraph architecture

## Production call chain

```text
HTTP/SSE (POST /turns/stream only)
   │
   ▼
TurnStreamService        ← SSE transport: one temporary worker thread per request
   │
   ▼
GraphTurnService          ← provider, reads, stop, deadline, progress sink
   │
   ▼
run_graph_turn            ← request receipt replay, then one fresh graph run
   │
   ▼
LangGraph (no checkpointer; one run per HTTP request)
   │
   ▼
START → load_context → understand
                          ├── retrieve ──┐
                          ├── mutation ──┤
                          └──────────────┤
                                         ▼
                                       answer
                                         ↓
                                       respond → END
```

`understand` chooses a conditional edge; there is no routing node. `respond`
commits plan changes, business context, messages and the final receipt together,
then publishes the final SSE events from those committed values.

Every HTTP request starts a fresh graph at `START` and finishes at `END`. There is
no checkpoint, no `interrupt()`, no `Command(resume=…)`, no back edge and no
run/thread/step binding. Multi-turn dialogue is durable because the **business
session store** keeps messages, task/plan versions, pending questions and shown
candidates; `load_context` re-reads them on the next request.

## Terminal SSE payload

`turn.completed.payload` is produced by `response_contract.build_graph_response` and always includes:

`request_id`, `session_id`, `task_id`, `state_version`, `session_version`, `status`, `answer_status`, `message`, `plan`, `plan_effect`, `pending_clarifications`, `available_actions`

## Clarification across requests

A clarification is an ordinary committed turn: `respond` persists the pending
question bound to the real target and the assistant message, then returns `END`.
The shopper's next message is a **new request** that starts a new graph;
`load_context` reads the same task/pending and `understand` attaches the answer to
the same real target id. There is no pause state machine and no second state
store. A pending is cleared when it is answered or when its target is committed.

## Progress events

SSE `progress` events carry only real phases: `understanding`, `retrieve`, `validate`.

## Storage responsibilities

| Concern | Owner | What it stores |
|---------|-------|----------------|
| HTTP receipt / idempotency | `TurnReceiptService` (`turn_request_records`) | Completed responses and recorded failures; digest conflict detection; replay before any model call |
| Business DB | `respond` node via `turn_commit.commit_graph_turn` | plan, task, versions, pending, displayed refs, messages, plan snapshots, receipt |

The receipt replay and SSE transport are intentionally **outside** the commit
node. They must not be folded into business mutation for "single write point"
convenience.

## Idempotency and stop

A `request_id` is one request identity: a completed request replays its stored
response; a recorded failure replays its original error (never a silent retry or
takeover); a request still running is `TURN_IN_PROGRESS`; a different body under
the same id is `IDEMPOTENCY_CONFLICT`. The transport persists no execution
record — no recovery query, polling endpoint or run lifecycle. `POST`
`…/turns/stop` only sets an in-process flag for the currently running worker;
a dropped SSE connection never stops the turn.

## Non-Guide APIs

`confirm`, `cancel`, `plan-refresh` and the explicit per-row add remain on their
existing services and do not enter this graph. The plan is never written straight
to the cart: an explicit confirmation still goes through the confirm interface.

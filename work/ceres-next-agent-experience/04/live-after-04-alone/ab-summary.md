# Ticket 04 fixed-case live comparison

Candidate: `04f5efde0c66d50213de72df266b7e692d2ca019` (clean), compared with the immutable before tree at `91ca0b80161dada5c83fa5955b8a27043172299d`. This is one development representative sample per case per arm, not a holdout or a quality estimate.

Both arms used the same frozen demo fixtures, seed code, test fixture and user inputs; fixture/seed hashes match. Each case built its own SQLite database and lexical index (`embedding=None`, `vectors=None`). Kev routing was controlled to the same branch per case; semantic/Mercury calls used the configured Qwen model. Configured model alias was `qwen3.8-27b`; response model tag was `qwen3.8-27b-fp8`. Physical model revision was not independently verified. This does not validate the default hybrid retrieval path.

| Case | Observed public result | Prompt tokens before → candidate | Calls before → candidate | Turn time before → candidate |
|---|---|---:|---:|---|
| `snack_type_first` | Baseline returned `EMPTY_PROPOSAL`; candidate asked for snack type with biscuit/chips options, pending `product_type`, no plan/cards. | 7,769 → 6,208 (-20.1%) | 1 → 2 | 4.57s → 14.16s |
| `same_category_cola_filter` | Both arms showed the single qualifying Coke SKU, prepared a plan without cart mutation, kept it after “好的”, and returned no match for the ¥1 filter. The fixture had only one qualifying SKU, so multi-candidate comparison was not exercised. | 41,640 → 32,386 (-22.2%) | 6 → 6 | 12.23s / 3.58s / 2.26s / 7.02s → 5.33s / 4.50s / 1.86s / 5.22s |
| `keke_return_policy` | Both answered from general policy sources and said the selected product’s eligibility was unknown; candidate also suggested checking the product’s non-returnable label. No application or plan was created. | 8,522 → 3,333 (-60.9%) | 2 → 2 | 7.44s → 11.22s |
| `momo_selected_order_return` | Both refused a return for the selected paid, not-yet-shipped order and offered whole-order refund as an alternative. `create_return` returned `ok=false`; public response did not submit a refund. Read-only case DB check found zero return/refund rows in both arms. | 5,382 → 5,400 (+0.3%; +18 tokens) | 3 → 3 | 5.42s → 5.34s |

All individual turns were under 15 seconds; the candidate snack clarification turn was 14.16 seconds. Every recorded Qwen HTTP call returned 200 and included usage. These are single observations; latency can vary with external service load, and this host did not measure unrelated concurrent Qwen traffic.

Each arm ran sequentially, with no overlapping calls within the four-case batch. The before evidence was written from 16:54–16:57 local time; the candidate evidence from 17:52–17:56. The candidate order was snack, Coke, policy, Momo. The collector was revised after the before batch to record per-turn Kev choice deltas and source hashes; the before Coke log contains 10 cumulative Kev records for four turns, while the candidate log contains four per-turn records. The controlled route and four public turns match; this is a telemetry-format difference, not an additional model call.

Full actual request messages/protocol/options, model responses, tool calls, usage and phase timings are retained in each local case JSON. Headers, Settings and credentials are not captured; request-key scans were clean and the credential redactor passed a sentinel probe. The sample outputs are kept under `live-before/` and `live-after-04-alone/`; the per-case command files record commit, fixture hashes, working directory and runner.

Candidate treatment is the ticket's prompt modularization and role/capability assembly, including ackend/app/llm/live_semantic_provider.py; these results do not isolate wording edits from prompt-composition changes. Business fixtures and retrieval/seed sources are unchanged.


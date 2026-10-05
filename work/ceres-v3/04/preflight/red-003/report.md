# 04 lifecycle red-003

- Scope: complete test_v3_switch_lifecycle.py (5 tests)
- Result: exit 1; 2 passed, 3 failed in 13.12s
- Runtime: Python 3.12.10, pytest 9.1.1
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: isolated per-run TEMP/TMP/basetemp; fixture-owned test DB; indexed_client uses its DB-bound lexical index; MEMORY_MODEL empty; controlled Kev/semantic/Mercury fixtures; inherited API settings cleared
- Source SHA-256: unchanged before and after

Passed:
- R08 shopping request from Momo returns to Keke after consent; plan SKU demo:eggs-fresh-6pack.
- Manual pending handoff resumes business once; later manual role selection restores role without rerunning business.

Failures:
1. test_momo_handoff_keeps_relevant_dialogue_and_resumes_existing_guide_state, line 109: guide planning completed and retained both cola and egg SKUs; Kev recent_dialogue contained the prior Momo user and assistant messages, but the resumed guide semantic request recent_messages omitted the prior Momo assistant reply. The relation=append fixture succeeded, so this is not a fixture-protocol failure.
2. test_display_quota_survives_get_rejection_and_role_switch_until_explicit_close, line 186: DELETE opening returned HTTP 405 instead of 204 after preceding quota/switch assertions passed.
3. test_unclear_object_clarification_does_not_assume_cancellation, line 203: terminal payload was turn.completed with message “你要取消的是采购清单项，还是已下单的订单？”, contrary to the test's requirement not to infer cancellation from “那个怎么办”.

The raw stdout is captured with --showlocals and contains failure locations, locals, and terminal payload context; see stdout.txt. No source/TASK/index changes or complete outbound traffic capture occurred.
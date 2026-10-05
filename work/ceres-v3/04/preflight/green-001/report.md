# 04 R08 green-001

- Scope: test_v3_switch_lifecycle.py::test_momo_shopping_request_returns_to_keke_only_after_user_consent
- Result: exit 1; the handoff/route assertions passed but the guide plan assertion failed.
- Runtime: Python 3.12.10, pytest 9.1.1
- Input observed by the test: “想买一盒新鲜鸡蛋”; the Kev utterance assertion passed.
- Fixture/query: “新鲜鸡蛋 6枚装”, quantity 1.
- Expected guide SKU: demo:eggs-fresh-6pack.
- Actual assertion point: completed["plan"] was null, so no final SKU was available to verify; indexing it raised TypeError.
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: per-run TEMP/TMP and pytest basetemp; MEMORY_MODEL empty; controlled Kev, semantic and Mercury fixtures; inherited API settings cleared
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and hashes are retained in this directory. No source/TASK/index changes or complete outbound traffic capture occurred.
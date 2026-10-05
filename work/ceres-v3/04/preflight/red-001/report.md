# 04 reverse-role red-001

- Scope: test_v3_switch_lifecycle.py::test_momo_shopping_request_returns_to_keke_only_after_user_consent
- Result: exit 1; expected red at opening(role=momo)
- Runtime: Python 3.12.10, pytest 9.1.1
- Failure: OpenRequest Literal validation returned HTTP 422, “Input should be 'keke'”; the test helper expected HTTP 200, so reverse-role opening was rejected before routing/switch assertions.
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: per-run TEMP/TMP and pytest basetemp; MEMORY_MODEL empty; inherited API settings cleared
- Source SHA-256: unchanged before and after

The raw command, environment, stdout, stderr, exit code and source hashes are retained in this directory. No source/TASK/index edits or complete outbound traffic capture occurred.
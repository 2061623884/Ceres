# 03 failed-handoff replay review-red-005

- Scope: test_v3_routing_handoff.py::test_failed_handoff_replays_failure_without_reexecuting
- Result: exit 1; expected review red
- Runtime: Python 3.12.10, pytest 9.1.1
- Failure: first switch attempt emitted a structured error. Repeating the same request returned HTTP 409 instead of replaying the first response (expected HTTP 200 with identical event text).
- The test also asserts Mercury generation ran once.
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: per-run TEMP/TMP and pytest basetemp; MEMORY_MODEL empty; controlled Kev and semantic fixtures; inherited API settings cleared
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and source hashes are retained here. No source/TASK/index changes or complete outbound traffic capture occurred.
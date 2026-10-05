# 03 explicit-order review-red-008

- Scope: test_v3_routing_handoff.py::test_momo_explicit_order_matches_router_and_business_instead_of_old_selection
- Result: exit 1; expected review red
- Runtime: Python 3.12.10, pytest 9.1.1
- Failure: the controlled Mercury model asserted that its prompt contained explicit order A. That assertion failed, and the final event was error rather than turn.completed.
- Correction to the earlier summary: do not characterize the Kev request state as selecting old order B. The failure occurred before the test's later state assertion, so that assertion was not observed. Per the source review correction, the router receives explicit order A while the business step still uses old selection B.
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: per-run TEMP/TMP and pytest basetemp; MEMORY_MODEL empty; controlled Kev and semantic fixtures; inherited API settings cleared
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and source hashes are retained here. The original stdout was not changed. No source/TASK/index changes or complete outbound traffic capture occurred.
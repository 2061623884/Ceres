# 03 actual-role review-red-006

- Scope: test_v3_routing_handoff.py::test_after_manual_switch_router_receives_actual_momo_role_and_order
- Result: exit 1; expected review red
- Runtime: Python 3.12.10, pytest 9.1.1
- Failure: after manually switching to Momo, the next Kev request received current_role=Keke shopping; expected Momo after-sales. The test also checks selected-order context after the role assertion.
- Warning policy: PytestUnhandledThreadExceptionWarning treated as error
- Isolation: per-run TEMP/TMP and pytest basetemp; MEMORY_MODEL empty; controlled Kev and semantic fixtures; inherited API settings cleared
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and source hashes are retained here. No source/TASK/index changes or complete outbound traffic capture occurred.
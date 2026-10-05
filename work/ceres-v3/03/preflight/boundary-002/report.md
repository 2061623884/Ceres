# 03 routing-context boundary-002

- Command: command.txt
- Environment and source SHA-256 before run: environment-and-source.json
- Result: exit code 1; 2 passed, 1 failed
- stdout/stderr: stdout.txt, stderr.txt
- Post-run source SHA-256: source-check-after.json; source_hashes_unchanged=true

The failing case was test_foreign_opening_and_order_are_rejected_before_model. The /turns/stream response began before route_context checked the order against the opening owner. OrderService.get_order() then raised 404 ORDER_NOT_FOUND; Starlette could not replace the already-started response, and the test client raised RuntimeError: Caught handled exception, but response already started. This is the expected security-boundary red: the foreign object must be rejected before streaming/model processing. The other two context cases passed.

The run used Python 3.12.10, pytest 9.1.1, warning-as-error, isolated TEMP/TMP/pytest basetemp, MEMORY_MODEL empty, and cleared inherited API configuration. No complete outbound traffic capture was performed. No source, TASK, or Git index was modified.
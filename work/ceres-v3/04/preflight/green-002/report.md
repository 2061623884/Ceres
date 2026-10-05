# 04 R08 green-002

- Scope: test_v3_switch_lifecycle.py::test_momo_shopping_request_returns_to_keke_only_after_user_consent
- Result: exit 0; 1 passed in 3.74s
- Runtime: Python 3.12.10, pytest 9.1.1
- Isolation: indexed_client and lexical index bound to isolated per-run temporary DB; MEMORY_MODEL empty; warning-as-error; controlled Kev, semantic, and Mercury SDK fixtures
- Verified original utterance: “想买一盒新鲜鸡蛋” reached Kev and continued to Keke after user consent.
- Verified guide plan SKU: demo:eggs-fresh-6pack
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and hashes are retained in this directory. No source/TASK/index changes or complete outbound traffic capture occurred.
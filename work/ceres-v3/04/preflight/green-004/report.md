# 04 反向交接上下文与已有进度 green-004

- Scope: test_v3_switch_lifecycle.py::test_momo_handoff_keeps_relevant_dialogue_and_resumes_existing_guide_state
- Result: exit 0; 1 passed in 4.26s
- Runtime: Python 3.12.10, pytest 9.1.1
- Isolation: indexed_client and lexical index bound to isolated per-run DB; MEMORY_MODEL empty; warning-as-error; controlled Kev and semantic fixtures
- Existing Guide plan: demo:cola-330ml retained.
- Original shopping request after handoff: “我想买一盒新鲜鸡蛋 6枚装”
- Added Guide plan SKU: demo:eggs-fresh-6pack
- Source Momo user message: “刚才问的是鲜鸡蛋 6枚装的退货期限。”
- Source Momo assistant message: “你问的是鲜鸡蛋 6枚装的退货期限；具体条件要以门店政策为准。”
- Assertions confirmed both Momo messages appeared in Kev recent_dialogue and in the resumed Guide semantic request recent_messages. The captured requests are from the controlled ScriptedSemanticProvider test double; this verifies the local provider-boundary payload, not live external network transmission.
- Source SHA-256: unchanged before and after

Raw command, environment, stdout, stderr, exit code and hashes are retained in this directory. No source/TASK/index changes or complete outbound traffic capture occurred.
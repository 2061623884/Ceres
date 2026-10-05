# 04 回归组 4 失败诊断（只读）

范围：仅复核 `work/ceres-v3/04/preflight/final-regression-012/group-04-guide-confirmation-journey/` 的原始证据、04 固定源码 ZIP、相关测试/协议与 02 已批准的一般政策边界。没有重跑 pytest、模型或 API；没有修改源码或 TASK。

## 失败计数

原始 `stdout.txt` 的短摘要为 **16 failed、14 passed**（第 1058 行），`result.json` 退出码为 1，且本组执行前后记录的源码摘要相同。逐项数原始 FAILED 行是 **16**：`test_phase2b_chat_confirmation.py` **14 个参数/用例实例**，`test_v2_integrated_demo.py` **2 个参数实例**。原 `report.md` 第 9 行说 Phase 2b 有 13 个实例，少计 1；应以 stdout 的完整失败列表为准。

## 14 个 Phase 2b 失败：测试夹具/检索环境问题优先，尚非已证实的产品回归

14 项全部停在共享 `_new_plan` 的首轮 `first["plan"]` 断言；确认、版本冲突、选中行、供给和预算等目标断言均未执行。失败回合的保留 `trace_events` 显示 `turn_result` 为 `status=understanding`、mutation `GOAL_TARGET_UNRESOLVED`。这是真实的“没有建出计划”，但不说明后续确认行为失败。

这里没有外部 `FakeSSE` 模型协议：`_new_plan` 用当前 `semantic_provider` 测试替身脚本化 `lookup_then_add("dish", "番茄炒蛋")`，随后通过 FastAPI `TestClient` 调用真实 `/api/v1/guide/sessions/{id}/turns/stream` 并读取其 SSE。`support/semantic_agent.py` 明确这是当前 one-pass semantic proposal（同一提案给出 target 与 lookup），与 `app/agent/protocol.py` 相符；终态已被解析成 `turn.completed`，所以原始失败不是 SSE wire/parser 失败。

首要夹具疑点是临时数据库没有配套的临时检索索引。`backend/tests/conftest.py::client` 只把 `DATABASE_URL` 和 `SOURCE_DATABASE_PATH` 指向本测试数据；本次命令的环境记录没有清除 `RETRIEVAL_INDEX_DIR` 或 `RETRIEVAL_MODE`，而项目 `.env` 中两项均非空，`Settings` 会读取根 `.env`。因此该 `client` 可能将临时测试库与项目级索引混用，lookup 未绑定目标正与 `GOAL_TARGET_UNRESOLVED` 一致。现有 `indexed_client` fixture（`test_semantic_phase1_purchase.py`）会从临时数据库构建 lexical 索引并显式覆盖这两个设置。测试 helper、semantic proposal fixture、protocol、read/retrieval、mutation 与设置文件的内容摘要均与 `baseline/source.zip` 相同；当前 04 的业务差异只在流入口传递 handoff context，没有修改该目标解析链。

建议最小处理：仅对需要先造出真实选购计划、再验证确认的这些 Phase 2b 用例改用现有 `indexed_client`，或在本票测试夹具中建立同等的隔离索引；不要改 production lookup、放宽 target binding，亦不要伪造完成的 SSE。专职 executor 先用一个代表路径验证计划可由隔离索引建立并进入原确认断言（建议 `test_ack_is_read_only_then_chat_confirm_buys_only_current_outstanding_rows_and_replays`），再运行剩余受影响的 14 个已选实例；当前证据不能断言固定 baseline 上也已复现，需把这一点留为未验证。

## 2 个 V2 集成旅程失败：与 02 新政策边界冲突的旧断言

两个实例都已成功完成购物车 checkout，然后在未选订单的 Mercury session 发送“这一单买了什么？”。测试把 `mercury.llm.OpenAI` 替换成必抛异常的 `forbidden_openai`，却仍要求聊天不调用模型、直接返回该 owner 的订单选项。因测试主动禁止了受控模型调用，SSE 没有 `final_text`，最终原始原因正是该断言被触发；这不是实模型回答错误。

该期待已被 V3 02 合约取代：未选单会话可以问一般政策，订单详情、资格和操作需要用户先选单。当前 `run_mercury` 对 session 未选单设置 `policy_only=True`，且 `openai_tools` 仅暴露 `search_after_sales_policy`；普通消息仍需要模型形成自然语言答复。“这一单买了什么”是订单详情请求，不能从全量列表/历史中自动猜出答案。02 的 `test_momo_can_consult_policy_without_selecting_an_order` 和 `test_unselected_policy_chat_rejects_even_unsolicited_order_tools` 已覆盖新边界。

建议最小处理：删除或改写这个过时的“聊天自动列出 owner 订单且完全不调用模型”断言。若保留此段旅程，用受控 Mercury 模型断言未选单工具集只有一般政策工具，并对订单详情请求回复先选择订单；随后走测试中已有的显式 order-selection API，再验证选中订单查询。也可以把一般政策问答直接留给 02 已有用例，避免重复覆盖。不要为恢复旧测试行为增加未选单的订单列表或自动绑定。

## 结论与后续验收边界

- 16 个 FAILED 行均已核清；14 个卡在 `GOAL_TARGET_UNRESOLVED` 的初始化夹具，2 个期待 V2 的未选单自动给订单选项行为，与 02 新契约不兼容。
- 暂无证据支持把这些失败归因于 04 的产品实现回归；Phase 2b 仍需按隔离索引定向执行以覆盖真正的确认行为。
- 相关测试与目标解析实现摘要等同固定 ZIP 基线，但本次没有在基线副本运行测试，故不声称“基线已重现”。Mercury 两项是测试契约陈旧的确定性问题；Phase 2b 的根因定位为高置信夹具配置问题，仍待 executor 只对代表路径验证。

## 证据入口

- 原始失败清单及最终计数：`work/ceres-v3/04/preflight/final-regression-012/group-04-guide-confirmation-journey/stdout.txt:1042-1058`；命令和隔离环境：同目录 `command.txt`、`environment-and-source.json`。
- 运行摘要：同目录 `report.md:3-10`、`result.json`；原测试回合的 `GOAL_TARGET_UNRESOLVED` 留在该运行 `pytest-tmp` SQLite 的 `trace_events`，未重放。
- Phase 2b 初始化/helper：`backend/tests/test_phase2b_chat_confirmation.py:92-97`；当前提案替身：`backend/tests/support/semantic_agent.py:5-8,248-272`；临时 DB 夹具：`backend/tests/conftest.py:107-109`；隔离索引夹具：`backend/tests/test_semantic_phase1_purchase.py:16-34`。
- 新政策合约：`tasks/ceres-v3-02-policy-consultation.md:10,16`、`docs/plans/ceres-v3-spec.md:80`；实现边界：`Mercury/mercury/agent.py:49-51`、`Mercury/mercury/tools.py:78-81`；新边界回归：`backend/tests/test_v3_policy_consultation.py:94-158`；旧断言：`backend/tests/test_v2_integrated_demo.py:196-211`。

固定 ZIP 内容摘要与当前文件对照显示：本诊断提及的 Phase 2b 测试/提案替身、协议/检索目标解析、V2 demo 测试及 Mercury agent/tools 文件均未相对 `work/ceres-v3/04/baseline/source.zip` 改变。本诊断未更改它们。

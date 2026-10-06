# Deadline 回归失败诊断

## 结论

专职测试器已在冻结候选上执行完整后端回归，并对 `test_agent_deadline.py` 前五个失败项做了聚焦复跑。聚焦复跑五项仍全部失败；原完整日志显示该文件最后两个 read-port 单测通过。现有证据将前两项归为已移除 JSON 接口的状态码断言，将第 3、5 项归为过期的进度替身，第 4 项归为脚本目标名与断言场景不一致。没有证据表明当前公共 SSE 回合的 deadline 或停止行为本身在这些用例中失效。

冻结候选 `HEAD=d3f426ecaf169bd01a7b86c137c61b9034d5079b`，源码 ZIP SHA-256 为 `094eb7d28777d5c3d7025bcad4aebd9f71a300cb275fe8679c9ec5cd825d2dfb`，312 个源码文件与 hash 清单零不匹配。与 07 pre-change baseline ZIP 对照，`test_agent_deadline.py`、`tests/support/__init__.py`、`turn_primitives.py`、`turn_progress.py`、`GraphTurnService` 和 `TurnStreamService` 均字节相同；07 后续 observer/docs 冻结没有改动这些失败链。

## 逐项因果

- **慢模型、慢读取：断言的是合成状态码。** 两个测试通过 `post_turn()` 调 `POST .../turns/stream`。实际入口是 SSE；内部 `GraphTurnService` 对未提交超时产生 503 `AppError`，流工作线程把失败送为 SSE `error` 事件。测试 helper 明确说明自己是“已移除 JSON `POST /turns`”的 SSE stand-in；它按 `retryable=true` 合成 502 `TurnHTTPResponse`。聚焦输出的 error JSON 已有预期的 `TURN_DEADLINE_EXCEEDED` 和 `retryable: true`，失败停在 `assert response.status_code == 503`。该 `502` 不是真实 HTTP 响应。当前 clock seam 仍有效：`GraphTurnService._monotonic()` 动态调用 `turn_primitives._monotonic()`；重放确实触发了预算耗尽。
- **模型返回期间停止、计划构建期间停止：没有向当前流回合发 stop。** 用例改写 `NoOpTurnProgressSink`，但公共流入口创建的是 `CallbackTurnProgressSink`，其 `should_stop` 读取实际 `stop_event`。因此补丁没有作用于正在运行的回合。第 3 项回到 `status=understanding`；第 5 项实际创建了 task，符合未收到 stop 的执行路径。迁移应在活跃 request_id 上调用当前 `POST /api/v1/guide/sessions/{session_id}/turns/stop` 并断言 SSE `turn.stopped` 与持久状态；也可仿现有 phase2a/2b 原子性测试用 `cancellation_registry.request_stop()`。`test_semantic_shared_contracts.py` 已有公共 stop API 用法。
- **先建两人份计划再同轮改两次人数：首轮脚本本身要求澄清，预期的第二次改动也未被脚本表达。** 原测试调用 `lookup_then_add("dish", "番茄炒蛋", "番茄", people=2)`；helper 将第三个参数作为模型目标名，所以脚本目标是“番茄”，lookup 查询才是“番茄炒蛋”。replay 临时 DB 的 `turn_request_records` 显示 `task_id=null`、`plan=null`、`committed=false`、`route=prepare`；该轮以 `understanding` 结束，返回 `dish` 澄清，原因是未找到与“番茄”完全同名的候选，选项包含“番茄炒蛋”。这是当前 exact/alias 绑定契约下的预期澄清；应把脚本目标改为完整名称，不能放宽运行时绑定。

  本次运行用 `semantic_provider` 安装的 `ScriptedSemanticProvider`，且进程 `LLM_MODE=offline`，不是实时模型请求。DB trace 只有一次 model-call started/completed，`input_summary` 为空；完整模型请求未被持久化。可由测试 helper 确定性还原的脚本提案目标名是“番茄”，不是声称拿到了实时模型原始请求。空 `MEMORY_MODEL` 的后台提取失败记录发生在 `turn_result` 之后，不解释这次 clarification。

  此外，`two_people_changes()` 只发出一个 `request_amend(... people=4)`，没有发出“再改成三个人”的第二个提案；但断言要求同一 turn 有一次 committed、一次 timeout。当前 `mutation.py` 写明它只准备变更，plan/task/cart 的唯一业务写入在 `respond` 的单一 commit transaction；headcount patch 无额外模型调用或 loop。因此该同轮部分提交场景不能从现有脚本或当前回合执行模型推出。聚焦运行在首轮断言处已中止，后半断言没有得到运行时证据。

## 最小迁移建议

- 前两项保留真实 SSE 入口：用 `stream_turn()` 读取 terminal event，断言 `type=error`、`code=TURN_DEADLINE_EXCEEDED`、`retryable=true`，再断言 session 无 task/plan 且购物车为空。已有 `test_semantic_shared_contracts.py::test_the_turn_deadline_is_a_failure_on_the_stream` 说明了当前 wire 断言方式。
- 第 3、5 项用实际 stop API 与 request_id，在回合活跃期间发出 stop；第 5 项可在当前 `CallbackTurnProgressSink.on_phase("validate")` 注入 stop 请求，同时保留原 callback 和真实 executor。不要补丁 `NoOpTurnProgressSink` 来模拟公共流行为。
- 第 4 项先用完整菜名建立已保存计划；第二请求只发一次 `people=4` amend。若要覆盖“准备变更期间预算耗尽，不写入计划”，在真实 `PlanChangeExecutor.prepare` 返回后推进时钟，使 `commit_graph_turn` 的 `final_guard` 在写入前看到过期，然后通过 SSE error 和数据库快照断言计划、购物车及版本不变。不要保留同一 turn 两次重建、一次已提交一次超时的旧 oracle。

## 边界与未验证观察

本诊断只读取既有 replay、测试源码、相关调用链、冻结 ZIP 和 replay 临时数据库；诊断 agent 未运行测试/模型/评测，也未改源码、TASK 或索引。`turn_commit.py` 另有一个边界：`TurnReceiptService.complete()` 之后，当前 `_refuse_unwritable()` 检查仅用于 `plan_effect == "clear"` 或 `verb == "confirm_plan"`，普通 headcount rebuild 随后直接走 `db.commit()`。因此在 receipt 完成后才推进 clock 并要求普通 rebuild 回滚，并非上述代码当前明确检查的路径；本只读诊断没有运行该场景，不能据此判为已确认 bug。建议这次采用 prepare 返回后、pre-commit `final_guard` 前的受支持边界，不增加新的生产 deadline 检查。

## 证据入口

- 聚焦复跑原始输出：`work/ceres-v3/07/evidence/deadline-replay-56141b699e484795bd0ad0a21e659f2f/stdout.txt`；退出码和冻结源一致性见同目录 `process-completion.json`、`source-before.json`、`source-after.json`。
- 详细临时响应/trace：`work/ceres-v3/07/evidence/deadline-replay-56141b699e484795bd0ad0a21e659f2f/basetemp/test_a_mutation_committed_befo0/test.sqlite3`（以只读模式查看）。
- 相关代码：`backend/tests/test_agent_deadline.py`、`backend/tests/support/__init__.py`、`backend/tests/support/semantic_agent.py`、`backend/app/services/graph_turn_service.py`、`backend/app/services/turn_stream_service.py`、`backend/app/agent/graph/nodes/mutation.py`、`backend/app/agent/graph/turn_commit.py`。
# 采购改选一致性与单道菜采购交付

日期：2026-10-04。TASK：[purchase-selection-and-single-dish](../../tasks/purchase-selection-and-single-dish.md)。

采购选择、金额、修订版本、确认请求及购物车新增的一致性已在限定用例中验证。单菜功能闭环的真实 API 固定用例独立两次通过；真实页面第二轮的附加 ACK 超时后，原清单保持不变，仍可明确确认。当前不能宣布模型响应持续稳定或两轮真实页面无异常通过，TASK 保留待验收。

## 根因与必要修改

页面勾选原本只修改 `planSelection`，没有写入服务端采购清单。原本未选的 pantry 行 `line_total_fen=0` 继续被用来计算金额；确认却提交本地新选择，后端拒绝为 `Must confirm exactly the selected snapshot items`。真实浏览器先复现了此价格与确认错误。

前端现在复用 `/guide/tasks/{task_id}/plan-revisions`，提交完整清单的数量和选择、现有会话/任务/方案版本。成功后更新现有 plan 及版本，移除重复本地选择状态；聊天与按钮确认都使用同一清单。显示金额和确认数量均以剩余采购量为口径，未选行小计为 0，合计只包含所选行。显式取消必需食材使用已有 `partial_ok`，显示仅采购勾选部分，不把未选项当作家中已有。修订复用已有 busy 状态，阻止同时修改、聊天或确认；没有新状态、队列或重试。

空选择仍保留可编辑清单，刷新可恢复并重新勾选；完成的历史方案沿用原来不提供可编辑清单的行为。普通 `plan_effect=keep` 回答不返回 plan，因此保留当前可确认状态，避免把预算不满足的方案重新启用。

单菜首轮实测发现推荐没有具体理由。只在既有系统选菜的 `full` 且 `can_confirm` 成功分支补充说明：必需食材已匹配当前可售商品、实际模拟金额、明确预算内；不新增推荐策略、模型调用或人数处理。受控公共 API 测试先两次失败，再修改后通过。

## 执行顺序与证据

第一阶段先通过，才执行第二阶段。运行库供给保持 321 SKU／321 Offer，未新增数据、全量 reseed 或改动活动索引。索引为 `idx-03d6c43d4eb25aff`，保留既有 `VECTOR_INDEX_MISSING`，不宣传为向量检索验证。

| 验证 | 结果与范围 | 原始证据 |
| --- | --- | --- |
| 采购改选公共 API | 改选及空选择恢复各独立两次通过 | `selection-tests.xml`、`final-related-tests.xml` |
| 最终前端改选闭环 | 两个独立 owner／session；受控模型 provider，真实页面、业务 API、运行库/索引副本。默认 1660 分，选油 2940 分，取消番茄 2260 分；刷新保持；明确确认后仅新增鸡蛋和油 | `ui-selection-controlled-1.json`、`ui-selection-controlled-2.json`、`ui-controlled-*-before.png`、`ui-controlled-2-cart.png` |
| 真实 API 单菜闭环 | 两个独立 owner／session；Qwen 实际请求。主推番茄炒蛋，初始 1660 分，选油后 2940 分；普通 ACK 不加购，明确确认结果匹配商品接口与最新清单 | `single-dish-1.json`、`single-dish-2.json` |
| 真实页面单菜闭环 | 两个独立 owner／session；需求、推荐、匹配、改选和明确确认均完成，购物车新增各 2940 分。第二轮 ACK 超时，保存同一修订清单后确认；不能称为两轮无异常通过 | `ui-single-dish-1.json`、`ui-single-dish-2.json`、`ui-single-dish-*-changed.png`、`ui-single-dish-2-result.png` |
| 相关回归 | 48 passed，1 skipped；跳过为原有 `baking plan not ready`。类型检查、Vite build 通过 | `final-related-tests.xml` |

真实 API 两轮推荐耗时分别 6463／3220 毫秒，ACK 2343／3820 毫秒，明确确认 19／14 毫秒。成功耗时不能代表持续稳定性。

全部失败保留：两次页面点名建单、一次修改推荐理由前的 API 建单、一次最终页面 ACK 的模型请求分别超时约 45.3 秒，详见 `failures.json`。诊断清单过期被拒绝的记录见 `ui-expired-diagnostic.json`；首次已完成但缺少具体推荐理由的回放见 `single-dish-before-reason-1.json`，其另一轮超时见 `single-dish-before-reason-2.json`。未增加 fallback、重试、宽泛异常捕获或调整超时配置；模型服务或网络侧的具体超时原因仍未知。

## 冻结与复现

- 基线为 `b71b592de5ad2d6d710339abe35d09b3807e17b2` 加已有 dirty 工作树，不能当作干净 HEAD 的结果。
- `before/` 保存本轮修改前的源码及既有测试依赖；`before/working-tree.patch`、`tested-working-tree.patch` 在本地记录修改前/最终已有未提交代码，其 SHA-256 见 `local-snapshot-hashes.json`。全量旧工作树补丁不纳入提交，快照不是本轮新增功能的提交范围。
- `frozen-selection-version.json` 为第一阶段；`frozen-version.json` 为增加推荐理由后的第二阶段，包含源码、测试、fixture SHA-256、模型和索引。不保存凭据。两个阶段各自固定用例使用同一阶段版本。
- `current-task.diff` 仅比较本轮前后；`recommendation-reason.patch` 是后端理由的最小补丁。
- 临时 API 使用现有测试 provider `ReactiveSemanticProvider`，运行库在线备份到 `ui-test.sqlite3`，索引复制到 `ui-test-retrieval-index/`；所有业务接口保持原实现。测试启动脚本只影响该临时进程，生产 8012 配置未改。临时 frontend 8444 将同一页面代码代理到 8013。
- SQLite、索引副本及截图留在本地。Windows Git LFS 的既有环境问题尚未修复，不修改 LFS 规则来提交这些二进制。

在 Ceres 根目录运行真实模型回放（会创建测试匿名身份并写入模拟购物车）：

```powershell
backend/.venv/Scripts/python.exe -X utf8 work/purchase-selection-and-single-dish/replay_single_dish.py 1
backend/.venv/Scripts/python.exe -X utf8 work/purchase-selection-and-single-dish/replay_single_dish.py 2
```

在 backend 目录运行本轮相关检查，不启动历史全量语义 A/B：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_purchase_selection.py tests/test_recommended_dish_purchase.py tests/test_pantry_plan.py tests/test_plan_revisions.py tests/test_revision_confirmation.py tests/test_confirmation.py tests/test_confirm_service.py tests/test_workflow_tomato_egg.py tests/test_system_meal_selection.py -q
```

## Standards

审查未发现硬性规范违反。两处剩余量乘单价分别用于行金额与合计，属于低风险的重复计算启发式；按 AGENTS 最小代码规则，不为它增加辅助抽象。新增推荐说明仅使用已校验计划事实，没有新增防御分支、状态或策略。

## Spec

审查未发现本轮代码范围扩张：默认角色、显式改选、服务端金额/版本、确认边界和现有会话接口均符合范围。两个真实 API 固定用例通过；真实页面第二轮的模型 ACK 超时如实保留，持续稳定性与无异常演示仍待验收。人数、长期记忆、供给扩充、换菜、追加与全量 A/B 没有纳入本轮验收。

## 提交边界与下一步

前端修复只暂存本轮相对 HEAD 可独立应用的改动，保留已有 UI/语义未提交工作。后端系统选菜函数本身属于既有未提交语义实现，在 HEAD 中尚不存在，因此不把整段旧实现或其他任务改动一并提交；当前工作树中推荐理由已生效并验证，其最小补丁保留在本次提交。采购改选回归提交至 `backend/tests/`；单菜新测试依赖既有未提交的 `test_semantic_phase1_purchase.py` fixture，因此以 `tests/test_recommended_dish_purchase.py` 快照提交，本轮实际运行的文件仍保留在 `backend/tests/`，避免在干净 HEAD 中引入缺少依赖的测试模块。后端补丁与单菜测试后续需随该既有语义实现合入，不能据此声称干净 HEAD 已完成本轮单菜验收。

下一步优先诊断四次固定模型请求超时；不扩大菜品、人数、记忆或多菜关联。本 TASK 的功能限定验证完成，持续稳定性保留待验收；旧语义和商品扩充 TASK 的状态与主会话不变。

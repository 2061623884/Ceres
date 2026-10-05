# 08 受控探索执行协议

本 harness 只准备、不代表执行结果。必须等 04 依赖完成并由主 Agent 明确安排专职 tester 后，才可从仓库根目录显式执行：

```powershell
$executionDir = '.\work\ceres-v3\08\execution-<unique-id>'
New-Item -ItemType Directory -Path $executionDir
& .\backend\.venv\Scripts\python.exe -X utf8 .\work\ceres-v3\08\exploration_harness.py `
  -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning `
  --basetemp "$executionDir\tmp" 1> "$executionDir\stdout.txt" 2> "$executionDir\stderr.txt"
$explorationExit = $LASTEXITCODE
$explorationExit | Set-Content -LiteralPath "$executionDir\exit-code.txt"
```

将 `<unique-id>` 替换为新建的唯一目录名；在 Ceres 后端测试所用的 Python 环境中运行。脚本调用现有 `backend/tests/conftest.py`、V3 handoff fixture 与 `indexed_client` fixture。它只把自身文件作为初始 pytest 目标，支持透传 pytest 选项（不要再附加其他测试路径），不会进入 `backend/tests` 或 07 core 自动收集。脚本通过 pytest `-s` 输出两例的 `CERES_V3_08_EVIDENCE=` JSON。执行前先建立本次专属目录；不要复用或覆盖已有执行目录。另记录 Python/依赖环境标识及实际命令。

## Harness 会做什么

- 每个参数例都用现有公共 API 创建独立 owner/Guide session/Mercury session 和新订单；不接触开发数据库或 Mercury 独立示例库。
- `delivered-return-requested` 例只在本例隔离 SQLite 中把 checkout 订单设为 `delivered`、把 `delivered_at` 设为当前时间前一天，并核实订单商品 `returnable=1`。`paid-return-rejected-then-explicit-continue` 例保持 checkout 原始 `paid` 状态。两例开始时均核对本单没有 return/refund 行。
- 先以 Momo 聊天公共 SSE API提交包含明确订单号和商品的退货请求。Kev、Mercury OpenAI 和 Keke semantic provider 都由已有测试替身控制；同步 HTTP 对非 Kev 测试域名一律失败。替身只选择真实 `get_order_details`、`create_return`、成功例的 `get_return_status`，业务工具及事务由当前 Mercury 实现实际执行。
- 直接只读核对本例数据库行和公开 Guide/cart 状态。成功应看到本单唯一 `requested` 退货申请、无退款；失败应看到 Mercury 工具 `NOT_DELIVERED` 且无退货/退款行。失败例在继续消息前必须看见无 Guide task/plan、购物车为空。
- 两例都必须由 driver 发送一条**新且明确**的“继续选可乐”用户消息；随后读取 `suggest_switch`，确认提示已展示，并通过 `switches/stream` 的 `accept=true` 明确同意切换，再观察 Keke 公共 SSE 和 Guide plan。成功例的申请仍为 `requested`；失败例的 `NOT_DELIVERED` 仍保留，Keke plan 不会把它改写成成功。该过程是观察者按 API 顺序驱动，不能称为服务自动推进。

失败例里“是否仍要继续选一瓶可乐？”是 harness 的受控 Mercury 模型替身固定输出；断言只确认该文本和业务拒绝经真实公共 SSE 返回。它不证明真实模型会询问，也不证明产品保存了等待继续的步骤状态。后续继续动作由测试 driver 明确发送，交接也由 driver 明确确认。

## 读结果时的界线

退货成功只表示 `returns.status=requested`（待审核），不是退货完成或退款到账；这两例不调用退款工具。失败是售后工具返回的业务拒绝 `NOT_DELIVERED`。它与 SSE 的 `error`（例如模型调用失败）是不同证据：尤其 `create_return` 事务先提交、最终答复模型后调用，若出现 `MERCURY_MODEL_FAILED`，先读本单数据库状态，不得根据 SSE 错误盲目重试。

当前 Opening 没有“第几步、退货结果、暂停/继续”的持久步骤状态。Harness 不写或模拟该状态，也不把受控模型答复当成编排状态。它只验证两个既有角色入口可通过新用户消息、真实提示展示/明确同意而串行调用。原话仅提交一次；V3 request_id 回执只针对相同请求标识，新的 request_id 重发同一原话未被这项探索验证，也没有跨步骤防重放依据，应作为残余风险记录。

受控模型确保可复现的工具/协议边界，不能证明中文真实模型质量、自然继续询问、开放式商品消歧、SSE 模型故障恢复、超时恢复或通用多步任务编排。若失败或出现与预期不同的 SSE/DB 状态，保存原始证据并报告 observations/failed；不得改生产逻辑或放宽断言来“修绿”。本探索不计入 05–07 核心完成率，且 04 未交付前不得运行。

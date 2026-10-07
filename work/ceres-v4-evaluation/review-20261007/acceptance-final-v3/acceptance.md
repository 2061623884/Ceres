# Ceres1 V4 自动验收记录

**结论：未通过。** 产品候选 `ac895fd620af617fa31f4e0006841a4d6a89cd53`；人工评测未执行。

60 场景、100 次计划执行；实际 100 次。业务达标 76/100，业务及适用性能达标 55/100；核心三次均达标 6/20。
有计时回合的执行 99 次，其中业务与性能同时达标 54/99。性能不适用 1 项（H20-r1）仅记录组件业务结果，不作为时延通过证据。
确定性检查发现关键违规 0；自由文本事实错误总数未知，不据此宣称全部事实正确。准备失败 0、脚本失败 0、未执行 0。
最终回复 ≤15 秒：134/162 回合。P50 5807.7ms、P95 30337.8ms、最大 71565.7ms。

| 分组 | 执行 | 业务达标 | 业务及适用性能达标 |
|---|---:|---:|---:|
| aftersales | 12 | 10 | 6 |
| drink | 15 | 11 | 4 |
| memory | 12 | 7 | 7 |
| policy | 10 | 10 | 7 |
| purchase | 19 | 10 | 8 |
| routing | 11 | 11 | 11 |
| snack | 11 | 7 | 4 |
| theme | 10 | 10 | 8 |

正常完成 74/98；合规拒绝 2/2。
生成可确认清单的执行 49 次，其中硬约束全部满足 39 次；该分母只包含已生成清单的执行，未生成清单仍在总执行分母内。

## 浏览器与组件

API计划100次与已记录的2条浏览器旅程分别统计；UI输入文件路径和摘要见机器记录。

- activity-salad：业务 passed；性能 False；阶段 explicit-confirm；失败动作码 无；超时 [{"label": "select-activity-product", "final_reply_ms": 15576.3064}]。
- snack-bubble：业务 failed；性能 True；阶段 request-plan；失败动作码 TARGET_NAME_MISMATCH；超时 []。

离线核对已记录的成功清单1份，覆盖小计/选中总额和适用预算；补充断言未重跑浏览器。检查见 acceptance.json 的 ui_assertion_review。

记忆样本定义覆盖显式写入/更正/删除/跨会话、owner 隔离、当前需求优先、临时预算与 Dream。Dream 的准备和内部触发属于组件验证；实际完成状态与已采集证据见逐执行记录。

## 裁判与调用

原始裁判捕获调用100次。顶层 enable_thinking=false 与 chat_template_kwargs.enable_thinking=false 的两个单条探针均耗尽推理预算、无可见 JSON，单列失败探针调用。最终诊断仅重放已捕获请求，采用源候选有效输出预算，保持推理配置不变，逐条保留可取得的请求、响应或错误，不执行产品任务。诊断分布 {"fail": 23, "pass": 36, "unknown": 41}，调用/解析错误 38；未人工校准、同模型，均不作硬门槛。

历史参数方案参考 [Qwen 官方部署文档](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md)；端点框架未独立确认，参数是否生效以已记录响应为准。存在可重放输入时使用原始捕获提示；发生离线评分更正时，旧提示不代表最新判分。语义发现须结合来源版本和最终业务记录复核，grounding 意见不替代对政策/检索实际来源的逐项核对。

| 组件 | 调用 | 有 usage | 输入 token / 覆盖调用 | 输出 token / 覆盖调用 |
|---|---:|---:|---:|---:|
| role | 140 | 138 | 676540 / 138 | 50925 / 138 |
| mercury | 43 | 43 | 76177 / 43 | 6702 / 43 |
| kev | 265 | 265 | 137292 / 265 | 19341 / 265 |
| background_memory | 44 | 44 | 13893 / 44 | 20629 / 44 |
| original_judge | 100 | 99 | 916378 / 99 | 118550 / 99 |
| diagnostic_judge | 100 | 91 | 858945 / 91 | 215907 / 91 |
| failed_probe_judge | 2 | 2 | 13704 / 2 | 2400 / 2 |

金额成本未知；不同供应商的原始 total_tokens 与 input+output 派生和分别保留，缺失不能按零估算。

## 失败与证据

以下失败按实际阶段归档，不推断根因。复跑须使用原批次 badcases.json 的独立输出目录和冻结候选；不会自动重跑。

| 执行 | 业务 | 失败阶段 | 超时回合 |
|---|---|---|---|
| R01-r1 | failed | choose-type | — |
| R03-r1 | passed | — | request |
| R06-r1 | passed | — | request |
| R07-r1 | failed | request | — |
| R11-r1 | failed | new-budget | — |
| R12-r1 | passed | — | request |
| R17-r1 | passed | — | consent-keke |
| R19-r1 | failed | list | — |
| H01-r1 | failed | independent-snack | — |
| H02-r1 | failed | clear-budget | — |
| H03-r1 | failed | accept-budget | — |
| H04-r1 | failed | confirm-added-quantity | — |
| H05-r1 | failed | choose-type | — |
| H06-r1 | failed | replace | request |
| H07-r1 | passed | — | policy-interruption |
| H11-r1 | passed | — | consent-momo |
| H12-r1 | failed | consent-keke | consent-keke |
| H15-r1 | passed | — | price, policy |
| H16-r1 | passed | — | request |
| H18-r1 | failed | request | — |
| R21-r1 | passed | — | request |
| R22-r1 | passed | — | request |
| R23-r1 | passed | — | request |
| R24-r1 | passed | — | stop |
| R25-r1 | passed | — | request |
| R31-r1 | failed | request | — |
| R32-r1 | passed | — | request |
| R01-r2 | failed | request | request |
| R02-r2 | passed | — | request |
| R03-r2 | passed | — | request |
| R05-r2 | passed | — | choose-type |
| R06-r2 | passed | — | selected-purchase |
| R07-r2 | failed | request | — |
| R11-r2 | failed | new-budget | — |
| R17-r2 | passed | — | consent-momo, consent-keke |
| R19-r2 | failed | list | — |
| R01-r3 | failed | request | request |
| R05-r3 | passed | — | selected-purchase |
| R07-r3 | failed | request | — |
| R08-r3 | failed | increase | increase |
| R09-r3 | failed | decrease | — |
| R11-r3 | failed | new-budget | — |
| R13-r3 | passed | — | request |
| R19-r3 | failed | list | — |
| R20-r3 | failed | delete | — |

完整分项与摘要见 [acceptance.json](acceptance.json)、[failures.json](failures.json)；原始 API、UI、诊断的绝对路径和来源 SHA256 均在 acceptance.json 内。产品修复任务见 [总 TASK](../../../tasks/ceres-v4-evaluation.md)。

## 条件与限制

- lexical only; hybrid not evaluated
- API first useful result time unknown (TestClient buffers SSE)
- UI timing is action start to fully received completed SSE; final text render latency not sampled
- Final UI subtotal/budget assertions added after run-02; passed plan checked offline, failed snack plan not reached
- Same-model semantic judge uncalibrated; diagnostics do not alter business/latency scores
- Diagnostic replay uses run-03 inputs; R14/R17 pilot hints predate correction and R17/H03/H12 hints predate completed assertions
- Judge inputs include business state/catalog facts but omit captured policy/retrieval requests; grounding findings are incomplete diagnostics
- Token sums have explicit coverage; no verified price and no UI provider usage capture
- For incomplete executions, call counts describe retained captures; uncaptured activity and usage remain unknown
- Observable deterministic critical violations do not establish zero free-text factual errors
- Original failed HTTP status may lack response body; see available state/trace, do not invent error code

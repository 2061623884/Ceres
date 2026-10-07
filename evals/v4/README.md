# Ceres1 V4 自动任务评测

规格见 [评测规格](../../docs/plans/ceres-v4-evaluation-spec.md)，状态与票据见 [总 TASK](../../tasks/ceres-v4-evaluation.md)。本套件针对用户确认的 ac895fd，保留原始失败；不会修改产品、自动重试或放宽门槛。

60 个场景分为 40 回归、20 新验收，20 核心各三次，共 100 次。运行前冻结；新验收不是统计盲测。记忆/Dream 单列组件，自动浏览器另记，不计入这 100 次 API 执行。

## 运行顺序

在仓库根目录，用已有后端 Python 环境运行。候选源码来自既有 `work/.ceres-next-08`。种子库与 lexical 索引的重建命令/配置/实际退出码保存在任务工作目录；不复用被产品执行污染的数据库。

```powershell
backend/.venv/Scripts/python.exe -X utf8 -m unittest discover -s scripts -p test_eval_v4.py -v
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py run --tree work/.ceres-next-08 --cases evals/v4/cases.json --seed work/ceres-v4-evaluation/runtime.sqlite3 --index work/ceres-v4-evaluation/retrieval-index --output work/ceres-v4-evaluation/run-01 --workers 2
```

`run` 默认只执行核心首轮 20 次，并生成以全部 100 次为分母的中间报告。核对脚本契约和评分规则后，才能继续剩余 80 次：

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py resume --output work/ceres-v4-evaluation/run-01
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py report --output work/ceres-v4-evaluation/run-01
```

每个 execution 都有独立子进程、数据库和 owner。恢复时检查评分器、样本、种子、索引、产品源码、配置文件和相关环境覆盖的摘要。已尝试的执行不自动重试，未完成的执行保留失败/未知。需要复现时使用 `badcases.json` 中的 argv 和新的输出目录，不覆写原证据。

项目规定测试由专职测试 Agent 执行；命令列在这里供复核与复跑，不表示主会话绕过该分工。

本次实际执行保留了首批 `run-01`。发现两项捕获/评分问题后，用原轨迹离线重评分至 `run-03`，再执行剩余 80 次；中间 `run-02` 也保留，不作为最终批次。历史评分器和最终执行版本不能混用，实际命令及冻结副本见工作目录 `evidence/run03-frozen/`。

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py correct-pilot --source work/ceres-v4-evaluation/run-01 --output work/ceres-v4-evaluation/run-03
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py resume --output work/ceres-v4-evaluation/run-03
```

以上目录已经存在，不重复执行这些历史命令。新的运行须选新的证据目录；`correct-pilot` 只适用于本次已定位的首批捕获问题。

最终审查补足 R17/H03/H12 的指定商品、数量、选中总额与可确认断言，样本规则版本为 v2；目标、输入、准备及执行次数不变。以已捕获状态离线生成最终评分批次，不重跑产品：

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4.py rescore --source work/ceres-v4-evaluation/run-03 --cases evals/v4/cases.json --output work/ceres-v4-evaluation/run-04
```

run-04 每条记录保留 run-03 来源 path/SHA256 与原始调用、时间；原冻结样本 v1 和执行器均保留。诊断仍重放 run-03 原请求，其旧评分提示不代表新版评分。

## 判分与记录

代码检查实际清单、购物车、Offer 金额、约束、订单/申请、授权及记忆状态。用户选商品和接受解释不等于确认加购；订单准备不算智能体成功。模型裁判仅作未校准的语义诊断。成功率分母包含全部计划执行，准备失败、脚本失败和未执行另计。

功能、每轮 ≤15 秒及关键违规分别报告；任一严格条件未满足，整体验收写未通过。TestClient 缓冲 SSE，API 首个有用结果时间没有客户端采样，保持未知。后台记忆等待与回复时间分开，费用缺可靠定价或完整 usage 时不填零。

最终原始证据、失败复跑入口和限制见任务工作目录，人工评测保持未执行；模拟商品价格、订单和脚本确认不代表真实交易或用户转化。

## 独立诊断与验收记录

原裁判大量耗尽 1200 推理 token，未产生可解析 JSON。顶层 `enable_thinking=false` 与 `chat_template_kwargs.enable_thinking=false` 的两个单条探针均未生成可见 JSON，分别保留于 `diagnostics-run03` 和 `diagnostics-run03-v2`，均未继续其余 99 条。历史参数依据 [Qwen 官方文档](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md)，但端点框架未知，本次未证明关闭推理生效。

`eval_v4_judge.py` 最终版只将已捕获裁判请求的 `max_tokens` 改为源候选有效配置的 3072，保持推理配置及其他字段不变；实际序列化请求和响应独立留证，原业务评分不变。v3 单条输出有效 JSON 后才续其余 99 条，不重跑产品任务。重放保留原始提示，R14/R17 首批评分提示早于离线纠正，语义诊断须结合最终业务记录复核。裁判输入未包含已捕获的政策/检索调用请求，grounding 意见有证据缺口，不能作为实际来源核对通过的证明；相关调用在 API 原始记录单列。

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4_judge.py --source work/ceres-v4-evaluation/run-03 --output work/ceres-v4-evaluation/diagnostics-run03-v3 --limit 1
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4_judge.py --source work/ceres-v4-evaluation/run-03 --output work/ceres-v4-evaluation/diagnostics-run03-v3 --resume
```

浏览器脚本 `scripts/eval_v4_ui.mjs` 使用 Playwright 和独立候选前后端。必需环境为 `CERES_UI_OUTPUT`、`CERES_APP_URL`、`CERES_UI_RUNTIME_RECEIPT`、`CERES_PLAYWRIGHT_MODULE`；运行 receipt 固定产品 HEAD、live/lexical 条件、进程、数据库、前端 URL 和实际提供的 App 模块摘要。启动命令与 receipt 保留于 `work/ceres-v4-evaluation/ui/`。

完整 API、UI 和诊断产物生成后，可在新的目录生成派生验收记录：

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/eval_v4_record.py --source work/ceres-v4-evaluation/run-04 --ui work/ceres-v4-evaluation/ui/run-02/result.json --diagnostics work/ceres-v4-evaluation/diagnostics-run03-v3 --probe work/ceres-v4-evaluation/diagnostics-run03 --probe work/ceres-v4-evaluation/diagnostics-run03-v2 --output work/ceres-v4-evaluation/acceptance
```

汇总记录分别报告主模型、Kev、售后、后台记忆、原裁判和修订裁判的调用与输入/输出 token 覆盖；派生 token 和供应商 reported total 分开，缺失或未核实费用仍未知。

UI `run-01` 因 parser/accessible-name/waiter 问题属于无效取证批次，仅保留历史证据。最终命令应指向修正后两旅程的 `run-02`，不能将旧 UI 失败误归产品。

最终审查另补确认前清单行小计/选中总额及零食预算断言，用 run-02 已捕获专题清单离线核对；零食原本未生成清单，仍为失败，不再重复模型/UI。执行时的冻结 UI runner 与补断言后的脚本分别留档，不冒称新脚本已做真实浏览器重跑。

# 07 同版验证与交接记录

冻结 v5 的新增 V3 模块回归、固定核心、真实 Kev/角色样本、首次留出及本批 Q20 检验均通过。历史全仓回归仍保留失败结果；正式 Cursor 页面和用户本人体验尚未验证。当前状态由 [07 TASK](../../../tasks/ceres-v3-07-final-acceptance.md) 维护，不将本记录当作整体已验收。

所有测试、模型调用和性能分析由专职测试 Agent 执行；主会话核对原始 argv、环境、PID、实际退出码、前后源码/数据摘要及实际回复。没有模型重试、重新选型或把失败记录改成成功。

## 同版最终结果

实际工作源码 ZIP：`a85bfc70c017999c01833c0969abf7217a4373c49673ca2ed750ef662a3a7dae`，312 路径，执行时 HEAD `d3f426ecaf169bd01a7b86c137c61b9034d5079b`。它包含继承 V2 的未提交改动；clean HEAD 不等同此 ZIP。各模型/回归组的前后 312 摘要无差异，源 catalog 为 `772a2d1c74bd112a01405aeefde7455f2c58e701e38d8186a29d24a52640be10`。

| 执行 | 实际结果 / 退出码 | 原始入口 |
| --- | --- | --- |
| 新增保存后发布/回放边界 | 1/1 passed；PID 74360、exit 0 | [deadline v5](evidence/deadline-candidate-v5-baeb9ba429994619b73362cdc27eeb88/process-start.json) |
| 全部 8 个 V3 测试文件 | 39 collected，32 passed、7 显式 live gate 自然 skip；PID 81492、exit 0 | [offline argv](evidence/v3-offline-candidate-v5-eb6363bbd35b46a1bba1c86c44294085/process-start.json) / [核心实际映射](evidence/v3-offline-candidate-v5-eb6363bbd35b46a1bba1c86c44294085/trace-summary.json) |
| 固定实际 Kev 路由 | 11 个场景各两次，22/22；PID 38104、exit 0 | [22 route 原始回执](evidence/live-route22-v5-0fec8e5ed7c0426f961237c6cf196ba9/model-evidence/results.json) |
| 实际 Kev + 角色 | 5/5 旅程，7 完整 API 回复计时；PID 37548、exit 0 | [role5 原始记录目录](evidence/live-role5-v5-089d7f42ae254264b4e23d0615847335/model-evidence/) |
| 首次独立中文留出 | HO01–HO04 全部通过；PID 47416、exit 0 | [holdout 原始回执](evidence/live-holdout4-v5-16391552984743c7b6d246e2ae472a60/model-evidence/results.json) |
| 性能分析器 | 输入完整，PID 59260、exit 0 | [原命令](evidence/performance-analysis-v5-3aa73880edae4536b4e81a0a506cfe2e/process-start.json) / [报告](evidence/performance-analysis-v5-3aa73880edae4536b4e81a0a506cfe2e/report.json) |

18 个预先固定的核心 case IDs 实际映射到 16 个 concrete pytest nodes，全部有 passed outcome，映射为空/缺结果均为零。32 个受控回归不是 32 个真实模型样本；7 个 skip 在随后三组显式真实调用中分别执行。真实路由组的角色业务受控；实际角色旅程为 R01、named-product variant、R02、R03、H01，R01 用户选款与 H01 同意交接另计两个完整响应。

Q20 按既定 protocol：指定 22 个常规路由的新增耗时 nearest-rank P95 **719.908 ms ≤1000 ms**，失败/缺计时 0；5 旅程的 7 个公共 API 终态回复最大 **11018.672 ms ≤15000 ms**，缺案例 0。本批通过范围是已加载模型、进程内公共 API/SSE；冷启动、正式页面等待分别验收。角色 R02 另有单次 route_ms=1046.493，原始值保留；P95 声明不代表每一单次调用都在 1 秒以内。

此次没有重测冷启动：01 既有实测加载 104.411 秒、首次推理 773 ms 独立保留，不并入常规样本。远端角色响应的波动及小样本限制保留，不由一次达标声称长期性能保证。

## 独立中文案例与实际回复

| 现象 | 期望 → 实际 | 结果 |
| --- | --- | --- |
| HO01 否定旧查单意图、转为购物 | stay_current → stay_current | passed |
| HO02 引用政策、尚未购买 | stay_current → stay_current | passed |
| HO03 回答了取消对象的澄清 | suggest_switch → suggest_switch | passed |
| HO04 同句自我修正后新选购 | suggest_switch → suggest_switch | passed |

四个主案例误建议切换、漏建议切换、clarify、失败、未同意角色改变均为 0；HO03 前置实际 Kev clarify 为一个单独 setup 观测，不当作第五留出案例。每种现象只有一个样本，不支持统计或广泛泛化结论。源标签、输入和分组自冻结后不改，留出首次执行后没有调参再宣称独立成功。详细分类见 [holdout-summary.json](evidence/live-holdout4-v5-16391552984743c7b6d246e2ae472a60/holdout-summary.json)。

主会话读了实际政策文本、选款后的数量 2 与待确认状态、H01 本轮订单，以及 HO03/04 未同意时的业务/购物车快照，见 [实际回复核对](primary-answer-audit.md)。一般政策有模拟门店条件及 P-RET-01/02 来源，没有选单前提或具体资格保证；suggest_switch 不执行目标业务。

## 模型、Prompt 与记录范围

Kev 固定 GPU 1 FP32，service source `fe64b1274ea7f80d4095866df90666abb03e9cf6`、checkpoint `139fdd94f1b6a6ad80cc15e08fcb99cac885a101`、base `1001bb4d826a52d1f399e183466143f4da7b741b`；实际 API 响应字段 `kev-latest`。角色配置名 `qwen3.8-27b`、实际响应字段 `qwen3.8-27b-fp8`；远端权重 revision 未提供，不宣称不可变权重身份。输出预算 3072。

各真实组的 `model-version-record.json` 保留源码/数据/Prompt/用例/protocol 摘要；Prompt 文件 SHA `9f53f25266359e6d87e4fd96827cc9655a79e40e591291000c3241c2e32fe603`，criteria version `ceres-service-v3.2`。token 仅使用实际 provider usage；字符数不当 token。06 的精简对照是单对样本，不由它声称稳定提速；本次 Q20 另在同版完整组检查。

offline 观察器保留 338 条记录：232 个 TestClient 响应中 223 个有 raw 字节，9 个流响应尚未缓冲；未主动消费流，缺失明确列于 [主会话 trace 核对](primary-audit-offline-trace.json)。parsed SSE 不冒称 raw 字节。真实组都有原始 API/SSE、上游 request/response 与 SHA sidecar。

## 全仓失败与定向修正

原完整回归在 **07 初始 candidate ZIP `094eb7d2…`** 执行全 121 个 backend 和 5 个 Mercury 测试文件，不是最终 v5：

- backend PID 72400、exit 1：1035 collected，938 passed、19 failed、57 skipped、21 setup errors、1 warning，1732.88 秒。
- Mercury PID 29180、exit 0：69 collected，61 passed、8 显式真实模型 skipped，4.17 秒。

原始入口是 [full backend](evidence/full-e5095afb1e2b4d19babc56f38e917212/backend/command-environment.json) 与 [full Mercury](evidence/full-e5095afb1e2b4d19babc56f38e917212/Mercury/command-environment.json)。修正的是旧公共 SSE/停止/fixture/ledger/SKU oracle，没有改生产行为；其中 16 个原失败用例定向通过，适用 v2/v3 ZIP 分开保存。新增 deadline v4 首轮失败后，v5 单节点正确复验通过，不能合成为“v5 完整 8/8”。首次 v2 deadline 执行退出码 unknown 未计入正式通过，另执行一次取得实际 exit 0。具体依据和原始路径见 [fixes.md](fixes.md)、[诊断](diagnosis/remaining-regressions.md) 与 `primary-audit-v2/v3/v4/v5-*.json`。

三项 W03/M1b 是 PROJECT 排除的 P1 购物车差额补货路径；尝试状态迁移后仍失败于缺少实际 scope question。本票没有新增差额算法，已还原 W 的全部基线字节，没有删或 skip 测试。21 个 RAG review setup errors 与 38 个缺快照 skip 源于缺少 Ceres 原 S1 `verification/data-completion/candidate_runtime.sqlite3`；邻项目文件来源无法确认为原快照，没有复制或重建后冒称 S1，见 [独立来源诊断](diagnosis/s1-snapshot.md)。定向绿灯与 V3 通过不改写原全仓结果，也不声称当前整个 backend 全部通过。

最终 Spec 沿调用方核对了这个范围：S1 交付材料将该数据库标为不进入正式运行路径的隔离检索候选库；21 项在 fixture 阶段失败，测的是 dish/SKU/index/过滤等继承数据面。V3 一般政策直接 `ReadTools -> policy_service.search_policies -> AfterSalesPolicy`，政策、路由与交接新增模块的公共 API 已在完整 V3 组和真实集成样本覆盖；此历史快照缺失不单独阻断新增 V3 验收。该判断不把历史 RAG 回归记为通过，后续恢复需独立源版本与实际执行证据。

## 审查、提交与页面交接

源码最终双轴：[Standards v5](review-v5/standards.md) 0 hard / 0 smells；[Spec v5](review-v5/spec.md) 0 源码遗留发现。它们审查时尚未得到后续 QA 结果，最终证据/状态出版复查另保存，不追写历史报告。逐版实际 ZIP 差异、继承 metadata 字段适用说明与 dirty 提交边界见 [source-provenance.json](source-provenance.json)。

启动/停止、两类 SSE、显示后 ACK 额度、主动切换与明确关闭/重入语义见 [V3 说明](../../../docs/ceres-v3.md)，公共 API body 见 [04 契约](../04/api-contract.md)。生产 `frontend/src` 未改；初步真实 API demo 可由启动后的 `/api/v1/chat/demo` 进入。Cursor 正式接入和本人操作按 [页面验收清单](cursor-acceptance.md) 留实际页面/API/版本证据，尚未执行。

08 仅交付有界探索报告，自动复合请求的持久顺序、暂停/续办能力未交付；不计核心完成率，见 [08 TASK](../../../tasks/ceres-v3-08-sequential-exploration.md)。

原始 stdout/stderr/metadata/SSE 用 lossless JSON 包装保留 CRLF/BOM 或原 bytes，映射见 [retained-raw-manifest.json](retained-raw-manifest.json)，不提交数据库、权重、索引、pytest 临时目录或源码 ZIP。README 的提交范围仅为本票 V3 入口。gap-persistence oracle 依赖 HEAD 尚无的继承 V2 fixture 迁移，工作文件保留，baseline→candidate patch 与源摘要交付，不将整份 V2 文件提交为本票代码，也不声称该测试版本已在 clean HEAD。

最终证据/状态出版复查：[Spec 出版](review-v5/spec-publication.md)、[Standards 修正后出版复查](review-v5/standards-publication-final.md)；历史 S1 的调用边界另见 [独立 Spec 核对](diagnosis/spec-evidence-boundary.md)。本票提交前静态结果与实际 index catalog 在执行后保存，不由源码审查推断。

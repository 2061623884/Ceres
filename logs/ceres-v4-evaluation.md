# Ceres1 V4 评测关键变化

当前状态只维护于 [总 TASK](../tasks/ceres-v4-evaluation.md)，这里记录变化及原因。

## 2026-10-07

- 用户确认 ac895fd 为产品候选，并批准先 `/to-spec`、再 `/to-tickets`、按四票实施。固定 60 场景 / 100 次任务、20 核心各三次、严格业务/授权/15 秒门槛；产品失败只记录，人工评测排除。见 [规格](../docs/plans/ceres-v4-evaluation-spec.md)。
- 产品与评测器隔离：产品执行来自既有 next-08 工作区，评测文件在 `codex/ceres-v4-evaluation`；不把 root 的已有 dirty 源码混入候选。保留源码归档、数据和 lexical 索引摘要，索引没有向量；因此本批不能作为 hybrid 条件的通过证据。见 [冻结清单](../work/ceres-v4-evaluation/source-freeze.json)。
- 首批固定 20 次执行后暂停并复核评分。R14 政策检查漏读 Mercury 调用，R17 helper 覆盖完整前态，均是评测器错误。用已经捕获的调用和相邻完整快照重评分，不重复执行产品任务，原始结果保留。run-02 是中间修订，run-03 修正 JSON 依据合并后作为后续批次；新增默认食材角色存在性负例。见 [原始首批](../work/ceres-v4-evaluation/run-01/report.md)、[修正记录](../work/ceres-v4-evaluation/corrected-pilot-evidence/corrected-pilot-verification.json)、[全量执行批次](../work/ceres-v4-evaluation/run-03/manifest.json)。
- 原模型裁判出现 `content=null`、`finish_reason=length`，1200 completion token 全部用于推理。原始诊断明确为 unknown；增加独立的诊断重评分入口，只重放已捕获请求并尝试关闭 thinking，不重跑产品任务、不覆盖原裁判、不改变业务硬门槛。调用依据是候选 MemoryProvider 已使用同一供应商字段，真实验证结果沿本地 TASK 记录。
- UI 首次批次暴露 parser 漏读候选 `data:{type,payload}`、可可按钮 SVG accessible-name 匹配失败，以及未处理的 waiter 拒绝。专题真实答复已显示但未被正确取证，另一条未完成，原批次记为无效评测器验证而非产品失败。保留旧冻结与产物，修正后仅重跑两条固定旅程；所有响应等待与动作即时绑定拒绝，SSE 原文先落盘再解析。见 [03 票](../tasks/ceres-v4-evaluation-03-browser-journeys.md)。
- 顶层 `enable_thinking=false` 的单条诊断仍无可见输出，未继续剩余 99 条，探针另存 `diagnostics-run03`。依据 [Qwen 官方部署说明](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md) 改用 `chat_template_kwargs.enable_thinking=false`，序列化请求与实际响应独立留证；端点框架未知，先验证效果再执行剩余诊断。原裁判/探针/业务结果各自保留，不混成一个产品任务分母。
- 两种关闭推理参数的实际响应都在 1200 reasoning token 截断，无可见 JSON；参数生效未获证明。第二探针的推理已在组织判分 JSON，因此最终诊断保持推理配置不变，只采用候选有效配置的 3072 输出预算。v3 单条产生有效四维评分，实际请求除 max_tokens 外与原请求一致，随后恢复其余 99 条；失败探针两次调用单列保留。原始提示中的 R14/R17 旧评分信息不改写，诊断发现须结合离线纠正后的业务记录复核。
- 本机 Git `core.autocrlf=true`；已冻结的样本、评测器和证据均以字节 SHA256 绑定，因此仅为本票文件增加局部 `-text` 属性，避免 Windows 签出转换行尾使摘要漂移。不修改原仓已有 dirty 根 `.gitattributes`。
- 最终双轴审查发现 R17/H03/H12 只要求清单存在、未完整核对指定商品/数量/金额，UI 确认前也缺清单小计/预算检查。补足规则后只用已捕获证据离线重评分到 run-04，保留 run-03 及诊断输入；目标、用户操作和100次真实执行不变。UI 新断言仅离线核对既有状态，不冒称新 runner 重跑过浏览器。
- 离线重评分也补判 H04 已失败确认步骤的数量要求：原失败记录未执行断言，实际购物车仅一罐而目标两罐。清单硬约束计数由 40/49 修正为 39/49；总体业务/性能结果不变，保留原字段缺失及新 checks，不改写原记录。见 [差异审计](../work/ceres-v4-evaluation/evidence/rescore-run04/hard-constraint-delta-audit.stdout.json)。
- 提交检查发现证据文件的原始 CRLF 被默认空白规则误报；为工作目录明确允许 CRLF，同时保留默认其他空白检查。唯一另有行末 padding 的原始 PowerShell 错误回执单独禁用空白检查；两份已冻结的审计尝试脚本保留其末尾空行，仅豁免末尾空行检查。保存原字节，不改写证据，不影响源码/样本/报告摘要。生产脚本和文档未出现此类问题。

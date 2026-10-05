# 02 Standards Review（只读）

基线 `a81a39d3a40f9f1bbb270961366cb5f6e930c664`；按 `review-scope.json` 只审查去噪后的 `source.patch` 增量，14 个源码哈希匹配；继承 V2 排除。依据 `AGENTS.md`、`docs/agents/domain.md`、`docs/agents/issue-tracker.md`，术语沿用 `GLOSSARY.md` 的“一般政策咨询”。

## 硬规范

**0 项。** 政策持久化/查询集中于服务入口（`source.patch:1-45`）；无新增兜底、异常吞没或无依据校验。未选订单时仅暴露政策工具，执行边界复核工具名（`source.patch:207-264`），新增参数有实际调用点。

## Fowler 启发式

**0 项。** 共用 `rank_policies` 有 Ceres 与 Mercury 两个调用方（`source.patch:276-312`）；`policy_only` 对应实际模式；ORM/HTTP 字段保持既有边界形状。Mysterious Name、Duplicated Code、Feature Envy、Data Clumps、Primitive Obsession、Repeated Switches、Shotgun Surgery、Divergent Change、Speculative Generality、Message Chains、Middle Man、Refused Bequest 均未形成可操作问题。

**Findings：0。** 仅静态审查；未运行测试或模型。

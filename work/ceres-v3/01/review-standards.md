# 01 Standards Review（只读）

固定点：`a81a39d3a40f9f1bbb270961366cb5f6e930c664`；提交列表为空。按 `review-scope.json` 审查 `source.patch` 中的单行变更及三份完整脚本，排除继承的 V2 dirty。依据 `AGENTS.md`、`docs/agents/issue-tracker.md`；未改源码/TASK，未运行测试。

## 硬性违规

未发现。唯一差异是 `amax-start.sh:11` 将缓存指到已校验的 `amax-direct-download/hub`（`source.patch` 对应 hunk），与执行证据中的真实缓存路径一致。未新增校验、异常吞没、默认值、重试或额外配置，符合 `AGENTS.md`「新增逻辑的依据」及反过度工程规则。

## Fowler 异味判断

未发现 Mysterious Name、Duplicated Code、Feature Envy、Data Clumps、Primitive Obsession、Repeated Switches、Shotgun Surgery、Divergent Change、Speculative Generality、Middle Man 或 Refused Bequest：启动脚本职责集中于固定环境启动（`amax-start.sh:3-15`）；runner 读取案例、构造单次协议请求并记录结果（`run-pilot.py:7-39`）；JSON 是对应的业务样例与预期（`chinese-pilot.json:2-9`）。差异仅是一处缓存路径，没有散改或重复逻辑。

判断项（非有效问题）：`run-pilot.py:34` 的 `body["answers"]["service"]["choice"]` 外观类似 Message Chain；但它只读取一次固定 HTTP 响应结构，本范围内没有可委托的领域对象，因此不构成可操作问题，也不应为此新增包装层。`chinese-pilot.json` 中的字符串标签是该单次 API 探查的协议值，不足以支持新增领域类型。

## 结论

有效问题：**0**。本结论仅覆盖上述 Standards 审查范围，不替代 Spec 审查或任务验收。

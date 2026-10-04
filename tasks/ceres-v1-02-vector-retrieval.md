# Ceres v1 02：真实向量检索

- 状态：待开始
- 负责人：本任务主会话
- 所属任务：[Ceres v1](ceres-v1.md)
- 依赖：[01 fixture 基线与最少补齐](ceres-v1-01-fixture-baseline.md)

## 范围与验收

复用现有 embedding、投影、build CLI、manifest 和 hybrid 查询；在 01 独立运行库上构建实际非空向量。显式 candidate-db、index-root、env-file 与服务配置一致，不另建 RAG 框架。

文档／向量数量对应最终投影，模型、维度及 query／document 指令契约一致。实际查询必须有向量分支证据，固定低词面重叠正例和跨类／明确条件负例符合预期；记录召回、融合、过滤及 query embedding 耗时。核实果汁与甜味依据在投影中。mock、仅有配置和词法降级不计通过；不修改旧评测 lint 或宣称缺失的通用 RAG 评测已经通过。

## 下一步与证据

待 01 输入固定后执行。证据放 `work/ceres-v1/02-vector-retrieval/`，记录源码、输入、索引及配置版本；数据变更后重建受影响索引，不沿用旧 321 索引冒充 v1。

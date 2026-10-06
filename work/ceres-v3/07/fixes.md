# 07 验证与审查修正依据

当前状态以 [07 TASK](../../../tasks/ceres-v3-07-final-acceptance.md) 为准。首轮全量实际候选冻结为 `094eb7d28777d5c3d7025bcad4aebd9f71a300cb275fe8679c9ec5cd825d2dfb`，继承 V2 未提交源码包含在 312 路径内；不是 clean HEAD 测试。原始失败不追写为成功。

## 独立留出观察器

Spec 静态审查发现建议切换的观察器仅核对首个路由事件、角色与订单，尚缺 `turn.completed.business_not_run=true` 及导购/购物车状态不变的证明。预备修正补齐这两项，并保留解析前原始 SSE、HTTP 和上游记录；输入、四个标签及分组不改。Standards 可选的同一记录重复赋值在此 hunk 一并移除。尚未执行真实留出前改良观察器，不把故障探针计为独立模型质量。

## deadline 旧测试与保存边界

依据 [独立诊断](diagnosis/deadline.md) 及五节点原始失败回放：前两项使用已移除 JSON 入口的 HTTP 503 预期，实际公共 SSE 的错误被测试 helper 合成为 502；错误仍是 `TURN_DEADLINE_EXCEEDED`，不是实际 HTTP502。停止测试触发旧 NoOp 回调，实际流使用 Callback sink；菜品脚本还把“番茄炒蛋”写成“番茄”，因此按当前名称绑定契约澄清。

已迁移为公共 SSE 超时终态及无业务写入断言，用真实 public stop API 停止回合，并明确完整菜名。单回合只表达一次人数修改；原测试脚本没有第二提案，不再用它要求双 rebuild/部分提交。提交前用例在实际 `prepare` 后推进时钟，核对旧清单、版本和购物车不变。v2 专项 7/7 通过，有实际 exit 0；首次同组记录未取得进程退出码，保留为 unknown，另一次执行仅用于补足退出证据。

Spec v3 要求补上实际单事务的提交后边界。新增用例在真实 `on_plan_ready` 发布后推进时钟，验证保存事实经 SSE、GET 和同 request_id 回放保持一致、购物车不变。v4 的完整 8 节点为 7 passed / 1 failed：新断言误把 `plan.ready` 的四个外层字段当作业务清单字段。v5 分别核对这四个字段，再比较完整清单；新增节点实际 1/1 passed、exit 0，后续 GET 和回放断言也执行通过。没有据此添加生产 deadline guard。v4 和 v5 是不同冻结版本，不能把两次拼为一次“v5 8/8”。

## P0 覆盖一致性

依据 [独立诊断](diagnosis/p0-coverage.md) 及三节点失败回放：共享准备缺少用户选择，只发送首次诉求就要求部分清单；实际为供给预览和 `supply_gap_choice`。准备现先验证无任务/清单/加购，再明确回答该问题；之后原有 session/revision/refresh/row-add 覆盖断言保留。v2 此文件 4/4 passed、exit 0；没有改生产逻辑。

gap-persistence 原本已有酸汤肥牛两阶段准备；本票只修正原 oracle：金针菇为 core 缺口，辣椒酱为 optional、数量未知的提醒。v3 该文件 4/4 passed、exit 0。HEAD 尚无继承的 V2 酸汤肥牛/opt-in/indexed-client 迁移，本票 hunk 无法独立应用于 HEAD；完整工作文件保留，owned patch 与两端源码摘要交付在 [review-v5/source.patch.json](review-v5/source.patch.json)，不将 V2 整份前置迁移提交为本票变更。该结论仅适用于冻结的 dirty 源码版本。

## 其余现行契约迁移与 P1 范围

依据 [剩余失败诊断](diagnosis/remaining-regressions.md)：已完成人数澄清以确认后的公共 GET 清单为基线；删除分组保留实际购物车内同 SKU 已购 ledger；品类用例使用真实临时 lexical index，保留实际商品、价格/库存证据及无加购断言；可乐鸡翅按菜谱的 ingredient/容量要求核对，不固定无品牌要求的 generic SKU。v3 对应四组分别 1/1、1/1、3/3、1/1 passed，均实际 exit 0。未改这些生产路径。

W03/M1b 三项尝试迁移顶层状态后，真实定向测试继续失败于缺少 `gap_fill_scope`。当前 PROJECT 明确排除购物车差额补货的 P1；没有实现该差额/零差额算法，也不删除或 skip 用例。W 源码已恢复本票前基线的全部字节，原全仓失败和尝试迁移后的 3 failed 记录保留。诊断中的初步迁移建议已被这次更深路径的实际证据否定，不能当作未执行的待修生产缺陷。

## 数据快照

RAG review fixture 要求 `verification/data-completion/candidate_runtime.sqlite3`，Ceres 当前未保留该文件。已独立核对邻项目同名数据，无法证明是 Ceres 原历史快照，见 [来源诊断](diagnosis/s1-snapshot.md)。没有复制邻库或重建后冒称原 S1；原全仓 21 setup errors 与 38 个缺快照 skip 保留。恢复需要 Ceres 原库/可验证归档与摘要，随后由专职 Agent 执行。S1 可乐单例的 oracle 失败与此快照缺失是两个不同原因。

## 同版功能验证与记录限制

v5 完整 V3 inventory：39 collected、32 passed、7 个显式真实模型 gate 自然 skip，实际 exit 0。18 核心案例映射到 16 个实际 concrete nodes，全部有 passed outcome。观察器原样保留响应，不主动消费流；232 条 TestClient 响应中 223 条有原始字节，9 条尚未缓冲，缺失明确记录，不用 parsed SSE 冒充 raw 字节。真实模型组另行执行，不把受控回归计为模型质量或性能通过。

所有执行由专职测试 Agent 完成；原始命令、环境、退出码、前后 312 路径摘要及 catalog 由主会话核对。逐版真实字节差异与继承 metadata 字段的适用说明见 [source-provenance.json](source-provenance.json)。完整仓库原回归仍是失败记录，定向修正和 V3 新模块通过不改写该历史结果。

# Ceres1 V4 评测实现 code-review 与修复

2026-10-07，用户追加授权 code-review 与修复。基线 `ee7ce104885f731bc48bc8c6338c00d802ba0619`，审查终点 `abd61394437f21c1b474d39c56559a245dc21e97`，命令 `git diff ee7ce104885f731bc48bc8c6338c00d802ba0619...abd61394437f21c1b474d39c56559a245dc21e97`；覆盖此前四个评测提交。修复复审比较 `abd6139` 与本轮工作树。规格为 docs/plans/ceres-v4-evaluation-spec.md，规范为 AGENTS.md、PROJECT.md 与 docs/agents/。

状态：修复及最终15项离线测试、5份Python源码编译、派生报告归档已完成，Standards/Spec最终只读复审完成，有效遗留均为0；交付待用户验收。未修改候选产品，未追加模型/API任务或浏览器执行，未推送。根目录原有 dirty 工作不纳入。

双轴结果：Standards 4项已修复，主要问题为失败分类丢失；Spec 5项已处理（含H20口径说明），主要问题为验收汇总与逐条事实不一致。两轴分别复审，无有效遗留。

## Standards

- ST-01：重评分读取准备/运行失败的缺省步骤字段会异常；即使字段存在也会改写失败分类。对应 AGENTS.md 的失败证据/状态要求。已让 report/rescore 共用 `execution_result`；仅对已正常完成判分的 passed/failed 重算终态，准备失败、脚本失败和未执行保留在分母。
- ST-02：归档器会原样嵌入陈旧的 summary.manifest 来源指针。派生验收记录现在使用实际读取的 source/manifest.json，原摘要文件与 SHA 不修改；新增端到端测试包含 obsolete-manifest 指针。
- ST-03：无UI/清单/探针/裁判输入的失败记录仍使用固定成功取证文案。四个负断言红测均复现；模板改为实际旅程、成功清单核验份数和捕获调用数，探针按是否执行描述，记忆定义与已采集证据分开，不夸大缺失证据。
- ST-04：04票“用户本人确认为待验收”的措辞易被读为用户已确认，与尚未验收冲突。改为“交付当前待用户验收”，不替用户确认状态。
- 已撤回：模块加载/已有数据库检查会触发未绑定局部变量的判断不成立。这些语句在 try 之前，异常不会进入该 except/finally；已有 launch 命令/退出/stdout/stderr及报告缺文件分类保留原失败，不添加额外捕获。
- 未发现需要按代码异味作形式重构的项。两项共享函数均有两个当前调用方，避免复制失败分类和汇总公式。

## Spec

- SP-01：中断 worker 留下 running 检查点，没有 performance_passed，report 抛 KeyError。红测已复现；现在只在派生读取副本中记 runner_failed/完成未知，原文件字节保持不变。
- SP-02：rescore 遇到 preparation_failed/runner_failed 会缺 unexecuted_steps；缺 result 会 FileNotFoundError。红测已复现两类异常；重评分保留各失败/未执行分类、原始错误和分母，缺原文件 SHA 为 null，有命令时另留其路径/摘要。
- SP-03：API/UI 汇总 gate 与逐条证据可以不一致。三个红测变体均被旧归档器接受；新归档器调用同一 `batch_summary` 逐字段核对，且核验固定两条 UI 旅程的状态与性能。矛盾在写输出前失败，不将旧汇总当业务事实。
- SP-04：无裁判输入或无诊断文件时不能完成失败批次归档。诊断器现在先冻结计划，对缺输入写 unknown 且不加载产品/发 HTTP；归档器对缺诊断保留 unknown、缺 SHA 为 null，并验证当前原始来源或重评分父来源。未执行探针时不强制要求探针；真实旧两探针仍验证并留档。100计划的测试覆盖1准备失败、1中断检查点、98未执行、100 unknown，以及缺1份诊断，最后仍能生成未通过报告。
- SP-05（口径说明）：H20 内部 Dream 没有用户回合，performance_applicable=false。55/100 是业务及适用性能口径，含1项组件业务达标；有计时回合的执行另报54/99，H20不作为时延通过证据。原始性能字段和总体未通过结论不改写。

规格依据分别为 User Stories 14–19、Testing Decisions 的组件/缺失信息边界与 Further Notes 的分母、分项汇总和证据要求。当前真实100条只有76 passed/24 failed，没有上述不完整状态；新修复没有把旧产品失败变成通过。

## 验证与证据

- 基线10项单测、Python编译与UI静态检查通过，见 baseline 记录。
- [中断红测](red-checkpoint/) → [11项绿测](green-checkpoint/)；[重评分两项红测](red-rescore/) → [13项绿测](green-rescore/)；[归档三变体红测](red-acceptance/) → [14项绿测](green-acceptance/)。
- [失败链红测](red-failure-pipeline/)使用旧提交中的精确冻结模块：旧 judge 复现 MissingCapturedJudgeInput；首轮旧 record 先在旧必填 probe 参数处退出，此次没有冒称触达后续缺文件/running守卫。补充适配旧 argv 的回执另留新目录。
- [最终15项绿测及编译](green-failure-pipeline/)通过；测试断言 HTTP 与产品加载未发生，保留命令、环境、stdout/stderr/退出码及代码 SHA。测试 Agent 不修改源码/票据或 Git 索引。
- 补充旧argv的红测实际在缺R03结果处抛FileNotFoundError，未到running守卫，见 [旧record实际失败](red-failure-pipeline/red-old-record-with-probes-attempt02/)。首次适配器路径错误与旧CLI拒绝均单列保留。
- [模板四变体红测](red-narrative/)及其精确冻结源码保留；最终E2E的6项负断言还覆盖无UI运行回执、无原提示的情况，9条真实诊断超时仅有请求/错误的口径经源记录核对。
- [最终15项绿测与5份源码编译](green-final-v3/)通过。[最终报告](acceptance-final-v3/acceptance.md)、[最终审计](acceptance-final-v3-audit/validation.json)确认477路径生成前后SHA一致、100条诊断来源回到run-03，业务76/100、业务及适用性能55/100、核心6/20、硬约束39/49、134/162回合≤15秒及45失败不变；H20单列N/A，有计时回合达标54/99。
- acceptance-rechecked/acceptance-final/acceptance-final-v2 是中间派生记录；最终派生记录为acceptance-final-v3，不覆盖旧acceptance/run-04/诊断/UI。版本间只有记录器源码按修复改变，全部原始数据保持不变。
- 提交前空白检查发现三份原始红测stderr首行含unittest的`... `进度空格。保留原始字节，仅以本目录.gitattributes对red-acceptance/red-narrative/red-rescore的三个精确stderr路径关闭blank-at-eol；文件末尾空行、tab前空格及其他文件检查继续保留。首次检查回执见final-precommit-validation.json。

任务当前状态仍由 tasks/ceres-v4-evaluation.md 维护；本文件记录审查发现、修复与证据，不把产品未通过写成已验收。

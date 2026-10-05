# 09 同版验证记录

所有测试、编译、模型和页面命令只由专职测试 Agent 执行，主 Agent审阅原始命令/环境/UTC/退出码/stdout/stderr。API受控结果、真实模型、页面与用户本人验收分别记录，不恢复历史全量语义A/B。

当前冻结候选：ae73702e64cf902d0da45b5276e0d8f9cd048f2fd0c73d6369d25aee6d1db03e，412文件，见source-inputs.json。相对已冷验证的c1c286候选仅改变PROJECT文档及live旅程两处错误状态断言，生产、fixture、索引、前端均不变；新目录逐文件412哈希已核对。先前411候选仅缺公开构建输入site.json，亦保留。复用Python3.12.10现有.venv、Node24.14.0/npm11.9.0现有依赖。cold目录来自归档；不是原工作树或clean Git checkout。

| 阶段 | 实际结果 | 证据及边界 |
| --- | --- | --- |
| 首次已有业务旅程 | 2pass/exit0 | run-a5aa9093aa6645ca93518fb9b3a66c73；lexical+外部模型受控，不制造RED |
| 初始冻结冷重建 | seed exit1 | 09-final-candidate-7bfef1d43be3437fafc742e3345db4c5；410hash匹配但遗漏scripts.import_db，未算通过 |
| 新候选两份hash/冷seed | exit0 | 09-final-candidate-77737bb5d22141c1bdfdcfa84ae64aa5；411/411各匹配，source=0，各65商品/65Offer/111模板（105菜谱） |
| 两份真实冻结索引结构 | exit0/pass=true | 同外部run，两份170 docs/FTS/vectors、1024维；V1真实向量复用，非新V2 embedding训练或质量承诺 |
| 新候选必要后端离线集合 | 161pass/exit0 | 同run，10个V2非live文件+purchase_selection/read_tools，198.89s；fixture-only、外部SQLite/index/basetemp；1条既有SyntaxWarning |
| 新候选Mercury离线集合 | 61pass/exit0 | 同run，agent_flows/tools/services/policy四文件，3.81s，无live_llm |
| 依赖记录 | pip freeze exit2；pip list exit0 | 既有editable元数据路径错误，未修共享venv；实际pip list --format=freeze清单位于最终UI批次，原receipt cwd错误另附更正；不是完整安装锁或新环境安装通过 |
| 411文件候选前端TS/build | tsc exit2、build exit1 | 同run，静态import的site.json不在包中；不是业务代码失败，原始日志保留 |
| 412文件候选两份冷启动 | seed/index各exit0 | 09-final-candidate-83f1c39408e649a495c633c23a4bbe4c；各412哈希匹配，65商品/65Offer/111模板、170向量索引；子进程直接退出证据，汇总PowerShell卡住只中断外壳，未伪造wrapper成功 |
| 412文件候选前端 | 两份tsc/build各exit0 | 同run，argv/env/UTC及raw输出齐全；外部新建dist；一次PowerShell原生stderr处理故障未给出可核build exit，保留并改用既有subprocess捕获方式 |
| 必要回归复用 | 161+61原结果复用 | archive-diff.json证明新包仅增加site.json，其他411哈希全部一致，无删除/变化，不宣称重新运行 |
| 最新语义修复真实06 | 6pass/2fail、exit1 | c1c候选同production单批8项；22.391/16.468秒未通过，临时讨论两次2.265/2.172秒无动作/无长期记录；explicit均保留、Dream两次成功，无重发 |
| 首次真实旅程 | 2fail、exit1 | 商品/默认勾选/23.40元清单实际正确，但脚本错误要求accepted，契约规定待确认是awaiting_confirmation；尚未执行其后业务，不冒充完整旅程 |
| 状态断言修复旅程 | 1pass/1fail、exit1 | 09-corrected-journey-fb5a1006ddc74188903a615f40009b75，59.36s；run1完整通过，run2在history查询16.953s仅速度失败，后续复购/结算/墨墨未执行；未重发06/冷构建/回归 |
| 隔离实际页面控件 | 2pass/exit0 | ui-orders-c417efc3a8464096a788c887ebf5e6b9/effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826；两个独立DB/新owner、真实Chrome DOM操作，无mock/业务状态注入/模型调用；不是完整聊天UI或本人验收 |
| 用户本人验收 | 待验收 | 本机指南十项均未由本人确认，不以API、mock或自动浏览器结果替代 |

06此前18.109秒及修复前22.11秒失败均保留。新Prompt的临时讨论两次无动作/无保存，行为缺口在有限样本中修复；速度仍失败。新stable-1主provider22281ms、conflict-2为16359ms，各一次调用；后台在turn_result后13/9ms才启动，分别约3.187/5.731秒。只读Trace无usage/finish_reason留存，不能区分网络与远端处理，不凭猜测改思考开关或缩短超时。conflict-2回复明确说“这次”理解当前陈述，未声称改保存，已有百事explicit未变，不定性为记忆覆盖错误。

原始回执先保留在产品父目录work/ceres-v2-test-env/对应UUID，完成阶段将复制明确文本文件至本票test-receipts；数据库、.env、clone、dist和缓存不提交。重建验证使用已装依赖，不代表新系统安装或全目录业务已通过。当前09仍阻塞，用户本人体验保持待验收。

## 修正旅程的逐运行边界

新包仅PROJECT与live测试两断言改变，source/fixture/index/frontend相同，412文件fresh clone核验exit0。完整有效pytest实际命令、cwd/环境/UTC与exit见该run的live-memory.command.json；文件标签虽为live-memory，其argv明确仅test_v2_integrated_demo_live.py，不与06混算。原始与safe副本均保留，根.env真实凭据/Bearer扫描未匹配。

run1：保存偏好2.578s，建单3.860s，清单取消番茄改选只选鸡蛋且确认前空车，明确确认；新session查历史10.125s、新4人方案10.000s，改选番茄并重新明确确认；checkout 0.016s生成O4fd67f7091cb484c/23.40元并清cart；墨墨未选单0.000s返回该真实ID，选单后真实咨询2.453s，未创建refund/return。全部断言通过，1pass不是两次。

run2：保存2.016s，建单7.812s，必需默认选/调味料不选与金额、改选鸡蛋0.015s、明确确认0.032s均通过；新session查历史16.953s返回真实来源、但超过15秒，流程停止。没有run2复购/checkout/墨墨证据，不能把run1订单归到run2。测试Agent先前简报混合两run时序，原输出按run核对后纠正，保留原报告不改日志。速度失败另做只读Trace，不刷样本。页面仅继续不依赖模型的确定性商品/cart/订单选单控件，不能当完整聊天UI验收。

## 实际浏览器控件的两个独立运行

主Agent编写ui-order-controls.cjs，专职tester执行。UI源码与ae73702e冻结候选相同；服务位于外部cold-journey目录，fixture分别65商品/65Offer/111模板。启动回执ui-services.receipt.json明确127.0.0.71:5171→8111→owner-71/ceres-ui.sqlite3，127.0.0.72:5172→8112→owner-72/ceres-ui.sqlite3；另建BrowserContext，不读原浏览器cookie或改8443/8012服务。测试配置LLM_MODE=offline、主/记忆模型及凭据为空。

有效通过批次UTC为2026-10-05T14:47:59.822800Z–14:48:10.907306Z，bundled Node调用Playwright 1.62.1及系统Chrome，实际进程exit0；场景SHA f571a0d8de1114858cfb3670e1766454e6359715c6059c027443773369cb3bbb。两运行分别为owner-924ba06f5fc543f2/O03b03ca2a93c47dd、owner-5135fa89114f4544/Oab816f8f5bab416f，每单番茄500克×1、680分。初始订单为空；商品按钮显式加购，点“结算”尚未提交，单独点“确认结算”后产生paid模拟订单并清空cart。刷新后GET与实际页面均保留同一订单；墨墨胶囊与新会话真实ID气泡分别手动选择本人订单。两例page_errors为空。只读数据库核对cart为空、两个选单session绑定真实ID、TraceEvent/model_call_started均0。

每例唯一聊天轮在未选单时询问“这一单买了什么？”，实际SSE仅返回本人订单选项，backend/app/api/mercury.py:96–98在模型前返回；选择后没有再问商品/发货或申请售后。故本批证明选单控件，不证明选后咨询；真实咨询仅此前run1支持，也不替代采购清单checkbox/历史聊天与本人体验验收。

历史失败全部保留：系统TEMP EPERM启动exit1、0案例；d6d9c58批次2fail在Avatar参与的按钮accessible name精确定位停止，仅显式加购；586811dd批次2fail在含“演示”徽标的heading精确文本定位停止，模拟结算已成功。主Agent只修正场景三处locator，业务断言、生产、15秒门槛不变，每次用新Context/owner定向复验，未重发模型或清旧失败数据。旧脚本与适用批次见ui-scenario-versions.json，原raw结果不改。命令、环境、截图与只读审计位于test-receipts/ui-orders-c417efc3a8464096a788c887ebf5e6b9；浏览器临时profile、DB、.env均不复制入Git。

测试服务清理仅针对核实完整命令行的41156/15344/24468/39992四个PID。清理记录器先有Windows PowerShell String.Contains重载错误（停止前），随后已停止但摘要漏传AttemptPath而exit1；两条失败不改成成功。独立只读service-cleanup-verification.command.json实际exit0，service-cleanup-verification.json确认四PID均不存在，8111/8112/5171/5172无监听；原服务未作为清理目标。pip list的cwd实际为产品父目录，单独cwd-correction.txt保留更正，argv/解释器/原输出不改。

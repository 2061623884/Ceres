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
| 依赖记录 | pip freeze exit2 | 既有editable元数据路径错误，未修共享venv；pip list版本清单另记，不当作完整安装锁 |
| 411文件候选前端TS/build | tsc exit2、build exit1 | 同run，静态import的site.json不在包中；不是业务代码失败，原始日志保留 |
| 412文件候选两份冷启动 | seed/index各exit0 | 09-final-candidate-83f1c39408e649a495c633c23a4bbe4c；各412哈希匹配，65商品/65Offer/111模板、170向量索引；子进程直接退出证据，汇总PowerShell卡住只中断外壳，未伪造wrapper成功 |
| 412文件候选前端 | 两份tsc/build各exit0 | 同run，argv/env/UTC及raw输出齐全；外部新建dist；一次PowerShell原生stderr处理故障未给出可核build exit，保留并改用既有subprocess捕获方式 |
| 必要回归复用 | 161+61原结果复用 | archive-diff.json证明新包仅增加site.json，其他411哈希全部一致，无删除/变化，不宣称重新运行 |
| 最新语义修复真实06 | 6pass/2fail、exit1 | c1c候选同production单批8项；22.391/16.468秒未通过，临时讨论两次2.265/2.172秒无动作/无长期记录；explicit均保留、Dream两次成功，无重发 |
| 首次真实旅程 | 2fail、exit1 | 商品/默认勾选/23.40元清单实际正确，但脚本错误要求accepted，契约规定待确认是awaiting_confirmation；尚未执行其后业务，不冒充完整旅程 |
| 状态断言修复旅程 | 1pass/1fail、exit1 | 09-corrected-journey-fb5a1006ddc74188903a615f40009b75，59.36s；run1完整通过，run2在history查询16.953s仅速度失败，后续复购/结算/墨墨未执行；未重发06/冷构建/回归 |
| 页面与本人验收 | 待执行/待验收 | 不以API或mock替代 |

06此前18.109秒及修复前22.11秒失败均保留。新Prompt的临时讨论两次无动作/无保存，行为缺口在有限样本中修复；速度仍失败。新stable-1主provider22281ms、conflict-2为16359ms，各一次调用；后台在turn_result后13/9ms才启动，分别约3.187/5.731秒。只读Trace无usage/finish_reason留存，不能区分网络与远端处理，不凭猜测改思考开关或缩短超时。conflict-2回复明确说“这次”理解当前陈述，未声称改保存，已有百事explicit未变，不定性为记忆覆盖错误。

原始回执先保留在产品父目录work/ceres-v2-test-env/对应UUID，完成阶段将复制明确文本文件至本票test-receipts；数据库、.env、clone、dist和缓存不提交。重建验证使用已装依赖，不代表新系统安装或全目录业务已通过。当前09仍阻塞，用户本人体验保持待验收。

## 修正旅程的逐运行边界

新包仅PROJECT与live测试两断言改变，source/fixture/index/frontend相同，412文件fresh clone核验exit0。完整有效pytest实际命令、cwd/环境/UTC与exit见该run的live-memory.command.json；文件标签虽为live-memory，其argv明确仅test_v2_integrated_demo_live.py，不与06混算。原始与safe副本均保留，根.env真实凭据/Bearer扫描未匹配。

run1：保存偏好2.578s，建单3.860s，清单取消番茄改选只选鸡蛋且确认前空车，明确确认；新session查历史10.125s、新4人方案10.000s，改选番茄并重新明确确认；checkout 0.016s生成O4fd67f7091cb484c/23.40元并清cart；墨墨未选单0.000s返回该真实ID，选单后真实咨询2.453s，未创建refund/return。全部断言通过，1pass不是两次。

run2：保存2.016s，建单7.812s，必需默认选/调味料不选与金额、改选鸡蛋0.015s、明确确认0.032s均通过；新session查历史16.953s返回真实来源、但超过15秒，流程停止。没有run2复购/checkout/墨墨证据，不能把run1订单归到run2。测试Agent先前简报混合两run时序，原输出按run核对后纠正，保留原报告不改日志。速度失败另做只读Trace，不刷样本。页面仅继续不依赖模型的确定性商品/cart/订单选单控件，不能当完整聊天UI验收。

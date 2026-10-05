# 09 同版验证记录

所有测试、编译、模型和页面命令只由专职测试 Agent 执行，主 Agent审阅原始命令/环境/UTC/退出码/stdout/stderr。API受控结果、真实模型、页面与用户本人验收分别记录，不恢复历史全量语义A/B。

当前冻结候选：c1c286f30f029040e199dcb2d8caf670b671aaa82ee1e41fc605f49c3d522eab，412文件，见source-inputs.json。上一份411文件候选见superseded-frontend-inputs.json，仅缺前端公开构建输入frontend/.figma/make/site.json；当前包补入原文件，运行源码、测试、Prompt、fixture与索引未变。复用Python3.12.10现有.venv、Node24.14.0/npm11.9.0现有依赖。cold目录来自归档，实际app/Mercury模块路径须记录；不是原工作树或clean Git checkout。

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
| 412文件候选冷启动与前端 | 待执行 | 补齐原构建输入后复核；161+61仅在未变文件哈希证明后复用，不宣称重新运行 |
| 最新语义修复真实06/旅程 | 待执行 | 各仅一批；<=15秒及不采购无动作均须通过，不重试/刷样本 |
| 页面与本人验收 | 待执行/待验收 | 不以API或mock替代 |

06此前样本18.109秒失败以及当前修复前22.11秒失败均保留。后者主provider唯一一次22015ms，后台在turn_result后7.555ms才启动；不采购却focus追问的原提案缺失，不能编造字段归因。新Prompt只澄清临时讨论且未修改/放弃时不改单，其效果待实际模型批次；速度仍未证明解决。

原始回执先保留在产品父目录work/ceres-v2-test-env/对应UUID，完成阶段将复制明确文本文件至本票test-receipts；数据库、.env、clone、dist和缓存不提交。重建验证使用已装依赖，不代表新系统安装或全目录业务已通过。当前09仍阻塞，用户本人体验保持待验收。

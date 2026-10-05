# 07 验证

专职测试Agent执行全部pytest/只读数据核查；Python3.12.10、UTF8、禁止pyc/cache，cwd=Ceres/backend。Ceres/Mercury数据库、索引和basetemp均外部UUID隔离；LLM_MODEL/MEMORY_MODEL为空，无真实模型调用，fixture-only65商品。每项参数独立数据库/owner/session；失败不重发，改源码或修正测试契约后用新run复验。

| run ID | 结果 | 范围与关键证据 |
| --- | --- | --- |
| 9f832a6e519a458d9a1062ae99dab272 | 2fail，exit1 | 首RED：协议未支持history，两次MALFORMED_PROPOSAL |
| d3fa73da51794638be2f47ecce82e581 | 2pass，exit0 | 首GREEN：历史源ID与新任务/新清单/默认选择，无加购 |
| 88784ad29c5847eeac757888e614f411 | 8pass/6fail，exit1 | 扩展：源件数和SSE字段测试假设错误；中文排除实际未阻止计划 |
| 50ec48fc043a4c8295c1dbe87651ea86 | 12pass/2fail，exit1 | 修正两测试契约及复用排除转换后，剩失败只为消息未显示鸡蛋排除条件 |
| 036cec598eb045d3968016585d0ed7ff | 14pass，exit0 | 最终代表性历史来源/当前条件/默认选择/修订确认，每例独立两次 |
| bc092d9f70954561a30b8251e511a0b9 | 55pass，exit0 | 01/02/03/05四组受影响回归，UTC11:26:24–11:27:48 |
| dc42d67ad7c24dc0963860d58f0075fa | 20pass，exit0 | 既有read tools补验，UTC11:29:08–11:29:17 |
| 45fb4e78d00745899215f1918cdab17d | 19pass，exit0 | history专用Prompt后14历史＋5外部provider错误，UTC11:34:10–11:34:39 |
| 4984800776a34696a700b34ce53ecb16 | 2fail，exit1 | 中文菜名历史查询RED，查询空结果使受控continuation失败 |
| 3af0a38453ae4e618764f6216e25d198 | 只读诊断，exit0 | 两个独立SQLite中，中文instr=0，JSON转义instr=9641；未写数据库 |
| 0453b1e74652488981575ed723b7ab69 | 21pass，exit0 | 修正查询编码后16历史代表项＋5provider错误；UTC11:46:28.613–11:46:59.267 |
| 8d64a414b0da4347a5029efe16bcb493 | 6fail，exit1 | 审查RED：缺行/共享数量误标完整；允许null贡献读取TypeError |
| 864f46fef7244f2589f5f0ae0568b395 | 42pass，exit0 | 修复后22历史代表项＋20read-tools，UTC12:02:09.866–12:02:53.738 |

test_read_tools.py最初被tester的路径正则误判不存在（Windows反斜线），主Agent已用rg核实并完成补验，不重复55项。随后只读代码核查发现通用检索Prompt强制唯一商品与历史菜品/多目标冲突，改为history专用回答提示，仍只读输出reply/display_refs；上述最小复验通过。中文名称查询另经RED→只读定位→一处编码修复→GREEN。双轴审查发现不完整件数与可空关联，六个独立RED后最小修复，42项复验通过。唯一验证范围为22历史代表项（各两次独立）＋75相关回归＋5provider错误；重复运行不累计为额外用例。真实模型理解/时长及本人页面体验仍待09，受控通过不替代真实验收。

实际命令、argv、环境、UTC时间、pytest退出码和stdout/stderr见test-receipts对应run文本；完整临时数据库在外部work/ceres-v2-test-env保留。本轮误复制入07的部分临时数据不纳入Git，只显式提交文本回执。

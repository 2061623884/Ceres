# 06 双轴审查

由两个独立只读 Agent 执行，未运行测试/模型、未读.env、未修改文件或Git。主 Agent判断发现并修复，测试只由专职执行 Agent完成。

固定点：ecec5b382cbf51f977a3d610c20aaf49fda60033。初审提交：ab77e63；命令`git diff ecec5b382cbf51f977a3d610c20aaf49fda60033...HEAD`。同时核查ticket-delta.patch、staging-receipt.json及source-hashes.json对应的实际工作树源码：Prompt与继承取消测试的本票增量只能作为patch提交，不将继承dirty源码整体提交。审查覆盖新provider/service、全部测试、诊断脚本与证据文件；本地提交不代表干净checkout完整冻结，09未启动。

## Standards 初审

1项硬性问题，0项Fowler气味。外部HTTP200异常外壳（空choices、缺message/content、content=None）可在provider抛未转换异常，绕过后台失败Trace。不满足AGENTS错误转换约定及本票后台错误记录契约。要求在外部provider边界精确转换、保留原因，不加宽泛捕获、重试或回退。

9个初审源码哈希与实际文件一致；继承部分仅看本票增量。15秒未过属于未完成验收，不能用59项受控通过替代。

## Spec 初审

1项代码契约缺口：同一外壳错误未进入memory_background_failed，违反实施规格跨会话记忆段和TASK06后台错误记录要求。两项文档问题已修正：将“轻量Dream”标题改为“低频Dream”；PROJECT补充06实现、采样、速度未过及停止边界。未见范围外功能。

真实批次7pass/1fail，18.109秒仍超门槛。只读Trace显示18.016秒集中于单次主provider调用，后台在turn_result后启动；更细耗时未知。此验证缺口保留，不能宣布已验收。

## 修复与复审

主 Agent新增公开聊天到后台Trace的外壳测试，四种外壳各两次。empty-choices两次RED未生成failure记录，同时worker抛IndexError；pytest2fail/2teardown error、实际exit1。随后仅provider边界将具体KeyError/IndexError/TypeError/ValueError转换为INVALID_MEMORY_OUTPUT，保留cause，非文本内容明确拒绝；截断错误继续单独报告。没有修改后台吞错范围或增加重试。

最终受控GREEN为fc958213e4524738a1b1a75bfb1a1f72，67pass/exit0，包含全部30项06及相关回归。两个轴的提交后复审回执待追加。速度门槛、全套原有失败/缺只读RAG快照与本人页面体验分别保留，不将这些项目记为已验收。

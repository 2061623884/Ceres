# 09 与全部V2增量双轴审查

正式固定点f41c5821e8764a0ae03653d161c566dfd4b6415e，已rev-parse确认且三点diff非空。实施/状态契约修复截至322c2378008016b8527b11a97258f9ad3133f390，共27个本地提交；后续页面/证据收尾另提交。不推送。

Standards与Spec由两个只读Agent分别执行，未运行测试、未读取.env、未修改源码/文档/Git。覆盖Git增量及v2-runtime-delta.patch/.json：相对接管时实际dirty快照的71个源/测试文件，以及全部09新增文件、执行脚本、原始回执和修复。artifact-only的Prompt、App、Mercury等实际被测源码纳入；71个SHA与当前工作树匹配，412候选ae73702e与归档回执一致，不把Git净diff当作完整候选。用户已保留qwen3.8并将速度阻塞留工程讨论，补审不发模型请求。

## Standards

生产与测试代码静态审查未见新增硬违规或应报告Fowler气味；08模拟订单/未发货文字已在实际App、Mercury和测试中核对。后续执行脚本副本发现硬规则问题1项：JSON日志解析使用except Exception；启发式观察1项：只读Trace脚本有if False死分支。主Agent分别收窄为JSONDecodeError、删除死分支，复审均关闭。原执行版保留在Git322c237和外部原件，当前副本只是静态修正版，未重跑；executed/static SHA映射见execution-script-review-fixes.json。

实际DOM场景与三处locator修正静态审查无新增问题；catch用于保留失败栈、另一独立case继续和最终非0退出，不吞错。历史脚本及适用批次见ui-scenario-versions.json，第一版是事后逆向两locator重建、非启动时hash留存，边界已注明。最终页面原始回执、只读DB/清理及依赖更正已提交本轴补审，结果待记录。

## Spec

预检发现的validation入口、依赖安装步骤、PROJECT/总TASK旧状态已修复；全新安装仍未验证。新live两处accepted断言按response_contract待确认契约修正，没有修改业务实现或放宽15秒。生产静态规格审查暂无未解决发现。

有效验收缺口仍存在：06真实6pass/2fail（22.391/16.468秒）；09真实1pass/1fail，第二条历史16.953秒后停止。实际浏览器控件两独立DB/owner均2pass，只验证商品加购、独立模拟结算、刷新订单和胶囊/真实ID气泡手动选单；选后咨询仅真实run1支持，不把控件冒充完整聊天、本人体验或两次全旅程。06/09保持阻塞，其他单票及本人清单待验收。最终新增回执与文档已提交本轴补审，结果待记录。

有效问题由主Agent最小修复，专职tester相关复验，两个轴覆盖修复和新增文件；不因纯风格扩大范围。最终分别记硬规则/启发式和产品符合性，技术失败不标已验收。

# 09 同版购买记忆订单演示交付

状态：阻塞
负责人：主 Agent；测试命令由专职测试子 Agent执行。
规格：[实施规格](../docs/plans/ceres-v2-spec.md)
依赖：[01 单菜人数到采购与确认](ceres-v2-01-single-dish-servings.md)、[02 明确多菜与共用食材采购](ceres-v2-02-multi-dish-demand.md)、[03 缺货规格适配与部分采购决定](ceres-v2-03-supply-adaptation.md)、[04 聊天可乐筛选比较到加购](ceres-v2-04-cola-comparison.md)、[05 显式跨会话记忆与聊天管理](ceres-v2-05-explicit-memory.md)、[06 后台自动提取与轻量 Dream](ceres-v2-06-automatic-memory-dream.md)、[07 历史方案参考到本次新采购](ceres-v2-07-historical-repurchase.md)、[08 模拟下单到墨墨选单咨询](ceres-v2-08-order-mercury.md)。

## 范围

在固定V2源码和模拟输入下完成有代表性的购买、跨会话复购和订单咨询连续旅程，交付可复现启动说明、最终双轴审查与本人验收清单。

## 验收标准

- [x] 集成必要回归由 tester执行，保存实际命令环境退出码和原始结果；没有失败标已验收
- [ ] 固定代表性流程两独立运行，保存源码/数据/索引/模型/Prompt及每轮时长，目标<=15s
- [x] Standards与Spec两个只读审查覆盖全部V2变动和新增文件，修复有效发现后相关复验（两轴剩余0，不代表业务门槛通过）
- [x] 启动及初始化说明可复现，示例不宣称真实交易/全目录/多用户效果（本机已有依赖，两份冷重建；全新安装未验）
- [x] 用户本人真实页面验收项目留待验收，并写明操作、期望和记录位置
- [x] 记录单票 Git 基线，红/绿与必要回归证据，本票提交、双轴审查与有效修复；不得推送。

## 测试边界

只运行01–08需要的集成回归/编译/模型和页面代表性流程，不自动恢复历史全量语义A/B。人工最终确认由用户执行。
所有测试命令委派专职tester，环境隔离；tester只运行报告，不改源码/测试/文档/TASK/Git。

## 阻塞与下一步

06最新真实8项6pass/2fail：stable-1=22.391秒、conflict-2=16.468秒，临时讨论语义两次通过但15秒未解除。09真实旅程1pass/1fail，第二条在历史查询16.953秒停止，不能当两条通过。用户选择保留qwen3.8、速度留待工程讨论，停止新增模型采样。两独立DB/owner的实际浏览器商品显式加购、独立模拟结算、刷新订单、墨墨胶囊和真实ID气泡手动选单2pass，主/记忆模型均未调用；本批只验选单控件，选后咨询只由真实run1支持。最终双轴复审与补证完成，两轴未解决问题0；无其他未受影响的开发/审查工作，速度项待工程讨论，本人确认待验收。不得整体提交继承dirty。

## 提交与证据

继承 Git HEAD：f41c5821e8764a0ae03653d161c566dfd4b6415e；本票基线0da93aec60721ca33609ab2ba40a1ba5b28d4ff2，见baseline.json；08文案修复另提交83ed7a6，09实施d920b07，新live断言修复322c237，实际页面与证据04a4f52。首次受控旅程2pass、必要后端161pass、Mercury61pass；两份冷重建及TS/build通过，源码哈希相同部分复用。live两断言按契约修正后1pass/1fail；原2fail回执保留。当前冻结ae73702e、412文件。实际页面控件两例通过的原始命令、截图、只读库/服务关闭回执位于work/ceres-v2/09/test-receipts/ui-orders-c417efc3a8464096a788c887ebf5e6b9/effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826/；此前环境/定位失败保留，未改生产。最终两只读轴复审剩余0及执行脚本最小复验见reviews.md、validation.md与review-script-recheck-e1650目录；仅精确本任务修复/文档/证据做本地收尾提交，不推送，不宣称全票通过。本机说明见docs/ceres-v2-local.md。

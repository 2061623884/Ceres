# Ceres V2 实施总 TASK

- 状态：进行中
- 负责人：本任务主 Agent
- 产品：[PROJECT](../PROJECT.md)；规格：[V2 实施规格](../docs/plans/ceres-v2-spec.md)
- 用户已授权在现有 Ceres 持续开发、自行记录常规技术决定和局部提交，不得推送；所有测试交专职只执行 Agent，Standards/Spec 分别只读审查。

## 票据与依赖

- [01 单菜人数到采购与确认](ceres-v2-01-single-dish-servings.md)
- [02 明确多菜与共用食材采购](ceres-v2-02-multi-dish-demand.md)
- [03 缺货规格适配与部分采购决定](ceres-v2-03-supply-adaptation.md)
- [04 聊天可乐筛选比较到加购](ceres-v2-04-cola-comparison.md)
- [05 显式跨会话记忆与聊天管理](ceres-v2-05-explicit-memory.md)
- [06 后台自动提取与轻量 Dream](ceres-v2-06-automatic-memory-dream.md)
- [07 历史方案参考到本次新采购](ceres-v2-07-historical-repurchase.md)
- [08 模拟下单到墨墨选单咨询](ceres-v2-08-order-mercury.md)
- [09 同版购买记忆订单演示交付](ceres-v2-09-integrated-demo.md)

按编号执行，独立业务在外部阻塞时可继续。01→02→03；05→06；02/03/05→07；04和08独立；09依赖01–08。每票的状态/验收/证据只在本票维护。

依赖票技术验证、提交和双轴审查完成后可推进下一票；本人体验验收集中在09，单票剩余人工项保持待验收。技术失败、未审查或外部阻塞不视为依赖已满足。

## 当前执行

规格与票据已发布，01即将开始。继承输入见 work/ceres-v2/00-baseline/；保留 V1 未验收项，不恢复历史全量 A/B。人工最终验收保持待验收。

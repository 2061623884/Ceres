# 02 明确多菜与共用食材采购

状态：待验收
负责人：主 Agent；测试命令由专职测试子 Agent执行。
规格：[实施规格](../docs/plans/ceres-v2-spec.md)
依赖：[01 单菜人数到采购与确认](ceres-v2-01-single-dish-servings.md)。

## 范围

用户明确追加多道菜，兼容食材先合计需求后按销售包装取整，保留每菜需求来源；人数/菜品/选择变化后重核金额到确认结果。

## 验收标准

- [x] 番茄炒蛋2人＋番茄蛋汤1人：番茄300＋125＝425g，1包500g；鸡蛋3＋1＝4枚，1包6枚，必需合价1660分，不按每菜包数相加
- [x] 分组来源完整，直接商品明确件数另加，用户改选及件数不丢失
- [x] 删除或改人数后共享量重算，已有分组和已购 ledger一致
- [x] 整份预算/排除保持，明确确认前不加购，最终购物车数量金额一致
- [x] 记录单票 Git 基线，红/绿与必要回归证据，本票提交、双轴审查与有效修复；不得推送。

## 测试边界

真实 Guide 和修订/删除/确认公共接口；共享需求/直接商品混合/人数修改各两独立运行，不引入全局优化或整餐推荐。
所有测试命令委派专职tester，环境隔离；tester只运行报告，不改源码/测试/文档/TASK/Git。

数字来源：data/fixtures/chinese-dishes-v1.json 的两道菜均基准2人；demo:tomato-fresh-500g为500g/680分，demo:eggs-fresh-6pack为6枚/980分。保留每菜300g/125g与3枚/1枚原需量，分别余75g和2枚。V2用例使用fixture-only供给，旧回归沿用原输入并单列。

## 阻塞与下一步

技术实现、验证、提交及双轴复审完成，依赖02已满足，继续03。真实模型及用户本人页面体验集中09，仍待验收；本票勾选代表受控技术验收，不代表人工体验通过。

## 提交与证据

本票基线9fc5a6c6140973a514e4a1123a4f42028fe40a24；实现8f26f35，审查补证b9bf972，均只含本票delta，不推送。继承源码与每文件before/hash见work/ceres-v2/02/baseline.json及ticket-delta.patch。

- 红/绿：共享需求由两菜各一包错误叠加，改为425g/4枚合并；取消勾选被重勾与已购ledger清零均先复现后修复。initial-green、selection-red/green、ledger-red、ledger-after-fix和full-green.json记录。
- 移组诊断为测试请求缺少现有ref/name契约的name，修正测试请求，未增加生产兜底。供给预览旧测试与新流程冲突、单菜消息未显示人数均在02前基线复现，分别校正测试和必要消息。
- 专职tester最终101项相关集合通过，实际退出0与raw已审阅；新增忌口约束2项通过（青椒肉丝实际含猪肉、100元足额预算），01相关7项亦通过。见final-green.json及review-fix-green.json。退出码遗失的一次中间成功摘要不作为正式回执，原记录保留。
- 前端tsc与外置Vite build通过，类型缺失已修复；剩余既有SyntaxWarning未扩大清理。
- Standards0明确违规/阻断；Spec最初1个忌口验证缺口补证后0剩余。见standards-review.md、spec-review.md及review-final.md。全部7文件含新增测试与修复均覆盖。

供给65fixture、lexical测试索引、脚本semantic provider；没有将离线结果宣称真实模型/向量质量/15秒页面证据。

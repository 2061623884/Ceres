# 08 双轴审查

固定点8420f0ea036f9b7187a20dc90cd79f8f70d91b35 → 实现0da93aec60721ca33609ab2ba40a1ba5b28d4ff2；实际工作树19源码路径与3份artifact-only按ticket-delta/source-hashes纳入审查。修复后21路径哈希均匹配。

## Standards

独立只读v1_reply_facts：初审1项硬性违规——App结算文案承诺门店备货，Mercury卡片暗示真实付款，违反AGENTS模拟交易/履约边界。另指出可能Repeated Switches，作为判断建议而非独立阻断，不为两处短状态显示新增抽象。修复后硬性问题0，需要处理的气味0。

## Spec

独立只读v2_product_audit：初审1项文案偏差，同样覆盖前端和Mercury状态事实。最小修复只调整四文件文字及原有测试期望，review-fix.patch保留准确增量。复审剩余0；未发现持久化/owner/选单/明确售后边界缺口或范围扩张。

## 修复复验

专职tester重新执行订单16参数项、Mercury61项及TypeScript noEmit，全部exit0。主Agent已读取实际argv、环境、UTC、exit、stdout/stderr；见validation.md。原始失败保留，未重复累加测试计数。真实模型、页面与本人体验待09；06速度失败未解除。

初始cached diff检查仅记录patch上下文空白及原始回执尾行警告，未当作源码测试通过；不改写原始证据以消除警告。

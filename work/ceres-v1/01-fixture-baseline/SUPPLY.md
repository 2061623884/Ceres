# 任务 01 最少供给补齐

核查日期：2026-10-04。已有 64 商品保持原记录，只新增 `demo:cn-minute-maid-peach-450ml-bottle`；最终 65 商品，56 条显式 Offer，9 条沿现有规则生成的 Offer。

## 已核商品事实

- 商品：美汁源汁汁桃桃桃汁饮料；类目 `beverage`，类型 `juice_drink`。这是果汁饮料，不标成 100% 果汁。
- [可口可乐中国品牌页](https://www.coca-cola.com/cn/zh/brands/minute-maid) 明确列出该桃汁饮料，口味描述为“甜而不腻”；据此记录甜味相关标签，不依据 original／zero 或糖含量推断。
- [中国食品 2025 中期报告](https://www.cofco.com/zljt/1/files/2025/0923/17586089059691089.pdf) 管理层论析中非橙口味规格升级段落，含“420ML转切450ML”及“汁汁桃桃”，说明 420ml → 450ml 的升级。[品牌官方包装图](https://www.coca-cola.com/content/dam/onexp/cn/zh/minute-maid-orange/peachset.png) 并列两种规格，核实 450ml 瓶装；未下载或作为本地商品图片使用。
- 名称、品牌及果汁／桃汁／甜味标签进入现有 `project_sku_row` 的检索文本。两次投影核对均含果汁及“甜而不腻”，不新增口味 schema。

## 模拟与未知

模拟 Offer 为 450 分／瓶、库存 30 瓶，`is_demo=true`；这一价格及库存不是品牌或零售商报价。规格为 450ml、每件一瓶；使用已有 placeholder，不宣称已有真实商超供货。

配料、过敏原、糖含量及真实条码未核实；`ingredient_ids=[]`，过敏原沿现有 seed 保存为 unknown，不制造食材映射、零糖或过敏原安全结论。数据 provenance 保留上述 URL 及核查日期。

## 供给不足案例保持

固定缺项候选仍用酸汤肥牛：64 基线有肥牛片，但没有金针菇；本轮只补果汁，不补金针菇。番茄炒蛋、蛋炒饭、青椒肉丝及宫保鸡丁的菜品池保留，最终业务匹配、选择与确认由 04／06 验收。

# V5 Spec review — initial source review

审查基线：原始本票前实际工作源码 ZIP `e91bbd5f0e02469d4cce9942d42763d75c4c64d6219c40b040fb7faa29c1382c`；HEAD `5462e999d583a9bab6147d0b4141d98321f3cc92`；候选 ZIP `06db637516e7b972cfafcbd563c72baaa9bedda7d357af7e613c0e88b57bb65b`。按 `review-v5/review-scope.json` 审查 14 条路径；14/14 SHA 匹配，10 项新增及 4 项生产文件在冻结范围内。与 v4 候选逐文件比较，v5 仅改 `test_v3_live_sampling.py`、`analyze-evidence.py`、`evaluation-protocol.md`、`fixes.md`；无新增生产改动。

### 缺失或部分满足

未发现静态实现缺项。R01 首轮保留原话与 `stay_current`，断言无 plan、未提交、无购物车写入且订单不变；从实际 `product_cards` 取固定 zero SKU，用户明确选择卡片名称并以该 SKU 的商品页上下文再发公共 API 请求，第二轮单独要求 stay_current、正常终态、准确 SKU/数量 2 和当前商品价格/可售库存（`backend/tests/test_v3_live_sampling.py:93-139`）。这符合既定 V2 可乐流程“比较、不自动选款，用户选具体卡片/ref 后才准备清单”（`backend/app/prompts/semantic.py:40`）；固定 R01 本身只定义服务路由与禁止项，并不要求首轮 plan（`evals/v3/core-cases.json:8-24`）。分析器必须有五个固定回执、R01 选款和 H01 确认共七个计时，缺观察或任一样本失败时不通过 Q20（`work/ceres-v3/05/analyze-evidence.py:36-59`）。

### 超出范围

未发现。R01 多轮旅程作为真实采样步骤与单轮路由标签分开；没有改业务 Prompt、V2 商品选择规则或生产代码。运行预算和前序模型/数量/服务准则调整沿用 v4 已审范围。

### 已实现但行为错误

未发现静态源码错误。尚无 v5 实际采样结果：不能据此宣称 R01 后续建单、五条角色样本或 Q20 通过。05 TASK 仍要求 18 项核心全通过并保留真实失败（`tasks/ceres-v3-05-baseline-evaluation.md:14,17-19`）；v4 首轮失败记录不得回写。此次只读审查未运行测试或模型。

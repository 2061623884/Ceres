# 一般政策最小 API demo

受控公共接口演示来自 preflight/fix-005-v3。可可：创建 guide session 后输入「这个商品不喜欢能退吗」，read policy 返回 P-RET-01 与 P-RET-02 条件及来源，task_id=null；墨墨：创建 session，不调用选单，输入「一般签收后几天内能退」，仅 search_after_sales_policy 可用，返回条件和 P-RET-01。两者 cart/order 不写入。

这组输入/输出不是正式页面或真实模型质量证据；03/04 提供可点击 API demo，正式 frontend 接入由 Cursor 完成。

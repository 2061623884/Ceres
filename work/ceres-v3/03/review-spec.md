# 03 Spec 复审记录

初审 Findings：3；最终 Spec Findings：0。复审基于 `work/ceres-v3/03/review-scope.json` 指定源码及本票 `source.patch`，10/10 文件摘要匹配；本记录保留初审。

1. **已修**：失败交接重复接受原会走 `HANDOFF_IN_PROGRESS`，把已失败状态说成仍在处理（初审 `chat.py:243-257`；违反规格 `docs/plans/ceres-v3-spec.md:68`）。现 completed/failed 均回放已记录 SSE。
2. **已修**：Momo 后续消息路由曾固定送入 Keke 当前角色，选单与历史也未取 Momo 会话；相反目标亦固定为 Momo（初审 `chat.py:97-120, 194-204`；违反规格 `docs/plans/ceres-v3-spec.md:11,54,58,62`）。现按实际角色读取对象/历史并动态选择目标。初始打开仍只支持 Keke 属 04 范围，不作为本票 finding。
3. **已修**：Momo 普通回合曾路由看显式订单 A、业务沿用选单 B（初审 `chat.py:104-108,131-139`；违反规格 `docs/plans/ceres-v3-spec.md:64`）。现普通 Momo 回合与 handoff 均按显式 `body.order_id` owner 重读并更新选单，路由历史按当前订单读取。

验证状态：`work/ceres-v3/03/preflight/final-regression-009-v3/` 为 exit 0，03 公共路由/上下文 10/10 通过，源文件运行前后摘要不变；它覆盖 A/B 新用例。此前 `review-green-007` 的9例为阶段记录。Kev 真实样例 `work/ceres-v3/03/calibration-v31/results.json` 为 5/8 匹配、3 次超时；不能计作质量通过，性能目标未通过。正式前端/04反向打开与退出周期仍未交付。

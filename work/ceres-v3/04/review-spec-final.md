# 04 Spec 轴增量复审

结论：增量复审未发现新的或未解决的 Spec 问题（0）。这是对初审的补充，不取代初审：初审固定在 `review-v1/review-source.zip`（SHA-256 `f4489083318adbf671a465ae4e0a55124f8bcb32b5b5973b712fd1965b3c6049`），原报告保留于 `review-spec.md`。

本次仅审查 Standards 修复后的两个增量：`backend/app/services/chat_opening_service.py` 删除 close 内重复的 registry identity guard；`work/ceres-v3/03/demo.html` 将 `sync` 更名为 `restoreChatState`。与 review-v1 ZIP 逐字节归一化后，服务文件只少这两行 guard，demo 除 5 处同一标识符替换外完全相同。close 仍在 opening lock 下拒绝已关闭/忙碌 opening 并从 registry 删除；名称变更不改变 demo 流程。两项增量均未改变 TASK04 与规格 `docs/plans/ceres-v3-spec.md` 的用户可见契约。

定向复验：公共 API close/reopen 生命周期单例 `1 passed`（exit 0）；Node VM 最小 DOM/mock API 的 inline consumer 生命周期复验 exit 0，`node --check` exit 0。首次 consumer 执行因 harness 直接 `await` 不返回 Promise 的 DOM onclick、未等待其异步处理而失败；保留该原始记录。重试副本只在两次按钮触发后增加 `settle()`，34 个既有行为断言全部保留且数量不变。该 Node 检查不是浏览器 E2E，也未启动真实服务或模型。

固定范围：HEAD `fbd9d01875eaeab5ec01e9849f4ce2bc562d1837`、本轮 commit list 空；review-source ZIP `53557616557f773d56020d956aceeb67a0bf5ddac97df6a0672b6b8b8f3657b1`，13/13 scope 摘要匹配。正式浏览器验证仍未由本次 Node 结果替代。

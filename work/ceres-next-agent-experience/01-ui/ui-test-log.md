# 01 UI 受控点击验证记录

Probe 使用 UI worktree 前端、bundled Node/Playwright/Chromium，模拟公开聊天 SSE；未调用真实后端或模型。

- 首次运行环境红：原仓 pnpm node_modules 缺失 `magic-string` 的 `@jridgewell/sourcemap-codec` 链接。未修补原依赖；在 UI worktree 用 `corepack pnpm@10.34.3 install --frozen-lockfile` 独立安装后解决，三份 package/lock SHA256 未变。安装记录见 `pnpm-install-frozen-output.txt`。
- 另一环境红：probe 曾错误覆盖浏览器 cache 路径；修正为尊重调用进程 `PLAYWRIGHT_BROWSERS_PATH` 后恢复。相关原始记录保留在 `ui-clarification-red-output.txt`、`ui-clarification-red-preserve-symlinks-output.txt` 和 `ui-clarification-red-clean-deps-output.txt`，均未到行为断言。
- 有效行为红：重复标签“薯片”气泡被点击后，出站 `/turns/stream` body 缺少 `clarification_answer`；预期包含当轮 question_id 与被点击 option_id。输出/运行记录：`ui-clarification-red-final-output.txt`、`ui-clarification-red-final-run.txt`。
- 首次绿测调试发现原气泡在后续轮次残留，薯片按钮数变为 4 而预期 2。实现者清除历史 assistant 消息上的旧 `clarificationOptions` 后，同一 probe 通过，输出/命令：`ui-clarification-green-rerun-output.txt`、`ui-clarification-green-rerun-run.txt`。
- `corepack pnpm@10.34.3 exec tsc --noEmit` exit 2，报告 `src/lib/chatOpening.ts` 中既有 `block.payload as ServiceRoutePayload` 的 TS2352；该 cast 在 HEAD 基线已有，未纳入本票修改。完整输出 `tsc-output.txt`。
- `corepack pnpm@10.34.3 run build` exit 0，Vite 生产构建通过。完整输出 `build-output.txt`。

## 后续类型检查

根会话决定在本票传输文件最小修复 HEAD 已存在的 `ServiceRoutePayload` 类型断言。未重跑已通过的受控 probe 或生产 build；只按指示重新执行 `corepack pnpm@10.34.3 exec tsc --noEmit`，exit 0，无 TypeScript 诊断。记录见 `tsc-rerun-output.txt`。

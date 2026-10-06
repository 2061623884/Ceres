# Standards review: precommit EOF fix

本次只审阅 EOF 修正、`remaining-regressions.md` 的当前内容，以及 precommit scope 规则；未运行测试或检查。

**Hard violations: 0. Possible smells: 0.** `eof-fix.json` 记录失败原因是末尾多余空行，修正前后仅移除 EOF 空行、保留 CRLF 和正文；当前文档为 7954 bytes，与记录的 7957→7954 修正一致。正文继续明确说明 11 项失败归因不等于修正后用例通过，未发现把未知结果写成通过或弱化业务契约的新增措辞。该文件位于 `work/<任务名>/`，符合 AGENTS 的执行证据归档约定。

`precommit_static_check.py` 将 candidate-v5 与声明的三项 publication-only edits 对照冻结的 312 路径（约 55、180–255 行）；stage 必须与经批准的 scope manifest 完全一致（263–280 行）。其拒绝两份继承 gap 测试、`.env`、`frontend/src/`、归档/数据库/模型文件、权重/索引及临时目录（282–306 行）。因此非归档形式的本票 candidate-v2/v3 迭代证据可由已批准 manifest 纳入；相应 ZIP 等归档仍被排除。README 还要求恰好新增一个 Ceres V3 TASK 入口（309–354 行）。这些规则与本票边界及 AGENTS 的任务范围、证据适用版本和不提交无关产物要求一致。

EOF 修正后的复验/precommit 是否通过不在本次只读复核范围内，不能据此推断。

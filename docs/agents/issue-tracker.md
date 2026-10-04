# Issue tracker: Local Markdown

Ceres 的问题、规格和实施任务使用本地 Markdown。任务入口沿用 `tasks/`，不另建 `.scratch/`，不向 GitHub Issues 发布任务。

## 路径与职责

- 现有较大任务继续使用 `tasks/<task-slug>.md`，例如 `semantic-contract.md`、`catalog-expansion.md` 和 `mercury-integration.md`；不因配置 skills 而迁移或重建。
- 已有设计、规格和证据保留原位置，由 TASK 链接。新增独立设计或规格放在 `docs/plans/<feature-slug>-spec.md`，不复制 PRD 或任务当前状态。
- 经用户确认需要拆分的实施票据，一票一文件，使用 `tasks/<feature-slug>-<NN>-<ticket-slug>.md`；从 `01` 按依赖顺序编号，并在所属任务中链接。未要求拆分时，不预先创建票据。
- TASK 维护当前状态、范围、负责人、验收、阻塞、下一步与证据入口；`logs/` 只记录关键变化及原因，执行证据保存在 `work/<任务名>/`。
- 状态沿用“待开始／进行中／阻塞／待验收／已验收”。skills 的默认 `ready-for-agent` 等状态模板不替代本项目状态。
- 阻塞关系记录对应票据的标题和相对路径；验收条件明确、依赖已满足的待开始任务才可执行。满足约定验收条件后才能改为已验收。

## 发布和读取

当 skill 要求“发布到 issue tracker”时，在上述本地路径创建经用户确认的任务或票据；优先更新同一任务的已有文件，不建立重复入口。

当 skill 要求“读取相关 ticket”时，读取用户给出的本地路径，或在 `tasks/` 按任务名称、编号查找，再沿文件链接读取设计与证据。

任务由对应主会话维护。评论与决定记在任务的相关段落；涉及多轮执行或交接的关键变化按 `logs/README.md` 记录。

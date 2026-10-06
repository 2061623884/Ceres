# S1 历史候选库缺失诊断

## 结论

无法证明当前两个相邻项目中的任一 `candidate_runtime.sqlite3`，就是最初随 Ceres RAG 测试预期使用的同一份历史 S1 文件。结论为 **unknown**。不应把任一邻库直接复制到 Ceres 并标记为原历史快照，也不能用 Ceres 当前 catalog 重建后声称是 S1。

Full1035 记录的 21 个 `test_rag_codex_review.py` setup errors 与该输入缺失相符。按当前证据，应把原 S1 fixture 作为未满足的测试前置条件；RAG 全套结果不记通过。若以后要恢复历史结果，需要取得 Ceres 原始文件 SHA，或能证明 ZIP 内文件 SHA 与原交接一致的 Ceres handoff。若要测试当前数据，应另立有明确版本、来源和 SHA 的新 test-local fixture，并把结果标为新基线。

## 已核对证据

- Ceres 的 `verification/data-completion/candidate_runtime.sqlite3` 不存在。`.gitignore` 的 `*.sqlite3` 会忽略此类文件；`git ls-files` 未列出该数据库。RAG review 测试及交付文档登记在提交 `9f8d7b5`。
- [`test_rag_codex_review.py`](../../../../backend/tests/test_rag_codex_review.py) 第 20–25 行直接从上述相对路径以 SQLite `mode=ro` 打开快照，再备份到 `tmp_path`；没有文件缺失时的 skip/fallback。[`test_rag_retrieval.py`](../../../../backend/tests/test_rag_retrieval.py) 第 43–46 行则在候选库不存在时跳过整个模块；`test_rag_eval_metrics.py` 第 128–130 行也跳过缺失快照的评测。
- Ceres 和两个邻项目的 `test_rag_codex_review.py` SHA-256 均为 `4959dde624a5cc2bd0df3de05600cd0b742e7c53b71d40b755f678560a3b007e`。Ceres 的 `test_rag_retrieval.py` 与 Sale-guide-langgraph 完全相同（`f3943653df15bffe7c34c5e42b1838beea1a6b6262d76cded450316b82dcad98`），与 Sale-guide 版本不同。这证明测试源在项目间相同，不证明数据库文件也一并复制或版本一致。
- 两个邻项目的 `handoff.json`、`data-contract.md` 和 `S1-delivery-report.md` 内容相同；handoff 标注 S1 完成于 `2026-09-19T00:45:00+08:00`，canonical `candidate_db_path` 指向 Sale-guide 下的数据库，`fixture_projection_hash` 为 `2adbb12fd4ee5cb9deb7eda227c200ede7cfc251ae7e4055d8deb872a14caf54`，并记录 source=257、demo=50、dish_templates=101、approved_catalog_total=307。该值是 projection hash，不是 SQLite 文件 SHA。Ceres 交付文档也记录此 projection hash 无法按仓库算法复核，`handoff_projection_hash_match=false`。Ceres 自己没有保留 handoff JSON。
- Sale-guide 当前候选库主文件为 610,304 B，SHA-256 `baa1bd2b1cf6f6a0ab2fcaa67935b187b06bb7030b7e59a5083ee2e13b4a47e8`；Sale-guide-langgraph 为 618,496 B，SHA-256 `6210c4c04217e5fb7b2352d5758a0ce00fda7fea589a3d158760472911c7f435`。两个主文件均以只读、query-only 方式检查，schema 表相同，但 `catalog_products` / `offers` / `purchase_templates` 行数分别为 307/307/107 与 308/308/111。前者更接近 handoff 的商品计数；后者文件时间为 2026-09-22 创建、2026-09-25 修改，且 handoff 仍指向 Sale-guide 文件。两份库的 SHA 和实际行数差异都排除了“它们是同一个文件”的说法。
- 只读检查 `work/ceres-v1/01-fixture-baseline/source-base.zip`，其中没有 `candidate_runtime.sqlite3`、`handoff.json` 或 `S1-delivery-report.md` 条目，未得到 Ceres 原始 SHA 或 manifest。

## 范围与限制

本诊断只读取测试源码、Git 路径记录、handoff/report、两个邻库及指定 ZIP 目录。没有运行测试、模型或评测，没有改源码、TASK、索引或数据库；本文件是唯一写入。由于没有 Ceres 原始数据库 SHA 或带该文件的 Ceres archive，不能把相邻项目的 S1 数据和测试结果认作 Ceres 的精确历史输入。

# 04 审查修复验证

Spec: 空比较结果时旧 refs 可重新显示。Standards: 去掉 load_context 的无效 or {}。
RED 065cf9c445424033b390b1165277b6ae: 2 failed, exit 1，UTC 07:30:48.3637522–07:30:53.9654503。
GREEN feef494683a041a2a961cdeeec6ff0ac: 完整 test_v2_cola_comparison.py 10 passed, exit 0，UTC 07:32:26.0936638–07:32:44.1644630。
命令: python -X utf8 -m pytest -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning tests/test_v2_cola_comparison.py [RED仅 ::test_empty_comparison_rejects_reused_prior_card_refs] --basetemp <run>/pytest-tmp。
专职 tester；cwd Ceres/backend；.venv Python；PYTHONUTF8=1/PYTHONDONTWRITEBYTECODE=1；外部隔离 DATABASE_URL/MERCURY_DB_PATH；RETRIEVAL_INDEX_DIR 空。原始日志在父目录 work/ceres-v2-test-env/run-<ID>，根已审阅。旧 SyntaxWarning 保留。没有前端改动，不重复构建。
本轮服务端对空 compare 清除 displayed，沿用现有 context 清除接口。受控语义/lexical，真实模型/UI 未由这些测试证明。

import hashlib, json
from pathlib import Path
from datetime import datetime, timezone
repo=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres')
work=repo/'work/ceres-v3/04'
run=work/'preflight/standards-recheck-013'
scope_path=work/'review-scope.json'
scope=json.loads(scope_path.read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
current={p:sha(repo/p) for p in scope['paths']}
api=json.loads((run/'api-lifecycle/result.json').read_text(encoding='utf-8-sig'))
node_first=json.loads((run/'demo/result.json').read_text(encoding='utf-8-sig'))
node_retry=json.loads((run/'demo-retry-002/result.json').read_text(encoding='utf-8-sig'))
delta=json.loads((run/'source-delta-check.json').read_text(encoding='utf-8-sig'))
old_scope=json.loads((work/'review-v1/review-scope.json').read_text(encoding='utf-8-sig'))
old_review=work/'review-spec.md'
report=work/'review-spec-final.md'
report.write_text(f'''# 04 Spec 轴增量复审

结论：增量复审未发现新的或未解决的 Spec 问题（0）。这是对初审的补充，不取代初审：初审固定在 `review-v1/review-source.zip`（SHA-256 `{old_scope['review_source_zip_sha256']}`），原报告保留于 `review-spec.md`。

本次仅审查 Standards 修复后的两个增量：`backend/app/services/chat_opening_service.py` 删除 close 内重复的 registry identity guard；`work/ceres-v3/03/demo.html` 将 `sync` 更名为 `restoreChatState`。与 review-v1 ZIP 逐字节归一化后，服务文件只少这两行 guard，demo 除 5 处同一标识符替换外完全相同。close 仍在 opening lock 下拒绝已关闭/忙碌 opening 并从 registry 删除；名称变更不改变 demo 流程。两项增量均未改变 TASK04 与规格 `docs/plans/ceres-v3-spec.md` 的用户可见契约。

定向复验：公共 API close/reopen 生命周期单例 `1 passed`（exit 0）；Node VM 最小 DOM/mock API 的 inline consumer 生命周期复验 exit 0，`node --check` exit 0。首次 consumer 执行因 harness 直接 `await` 不返回 Promise 的 DOM onclick、未等待其异步处理而失败；保留该原始记录。重试副本只在两次按钮触发后增加 `settle()`，34 个既有行为断言全部保留且数量不变。该 Node 检查不是浏览器 E2E，也未启动真实服务或模型。

固定范围：HEAD `{scope['baseline_head']}`、本轮 commit list 空；review-source ZIP `{scope['review_source_zip_sha256']}`，13/13 scope 摘要匹配。正式浏览器验证仍未由本次 Node 结果替代。
''',encoding='utf-8')
checks={
  'captured_at_utc':datetime.now(timezone.utc).isoformat(),
  'review_kind':'incremental Spec-axis review after the two Standards fixes; initial review is preserved separately',
  'baseline_head':scope['baseline_head'],
  'commit_list':scope['commit_list'],
  'prior_review_zip_sha256':old_scope['review_source_zip_sha256'],
  'prior_review_report_sha256':sha(old_review),
  'current_review_scope_sha256':sha(scope_path),
  'current_review_zip_expected_sha256':scope['review_source_zip_sha256'],
  'current_review_zip_actual_sha256':sha(work/'review-source.zip'),
  'current_source_patch_sha256':sha(work/'source.patch'),
  'scoped_path_count':len(scope['paths']),
  'scoped_path_hashes_match':all(current[p]==scope['sha256'][p] for p in scope['paths']),
  'current_path_sha256':current,
  'standards_delta_normalization':delta,
  'focused_api_test':{'run_id':api['run_id'],'exit_code':api['exit_code'],'stdout_sha256':api['stdout_sha256'],'stderr_sha256':api['stderr_sha256'],'source_hashes_unchanged':api['source_hashes_unchanged']},
  'node_first_harness_run':{'exit_code':node_first['exit_code'],'stderr_sha256':node_first['stderr_sha256'],'failure':(run/'demo/stderr.txt').read_text(encoding='utf-8'),'classification':'harness did not await event listener that returns void; preserved as original failure'},
  'node_retry_consumer':{'exit_code':node_retry['exit_code'],'syntax_check_exit_code':node_retry['syntax_check']['exit_code'],'stdout_sha256':node_retry['stdout_sha256'],'stderr_sha256':node_retry['stderr_sha256'],'syntax_stderr_sha256':node_retry['syntax_check']['stderr_sha256'],'harness_assertions_preserved':json.loads((run/'demo-retry-002/harness-adjustment.json').read_text(encoding='utf-8-sig'))['assertions_changed'] is False,'browser_e2e':False,'live_backend_or_model':False},
  'unresolved_spec_findings':0,
  'report_sha256':sha(report),
  'review_scope_fixed_point_inherited_v2_excluded':True,
}
(work/'review-spec-final-scopecheck.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'report':str(report),'report_sha256':sha(report),'scopecheck':str(work/'review-spec-final-scopecheck.json'),'scopecheck_sha256':sha(work/'review-spec-final-scopecheck.json'),'scoped_path_hashes_match':checks['scoped_path_hashes_match'],'api_exit':api['exit_code'],'node_first_exit':node_first['exit_code'],'node_retry_exit':node_retry['exit_code'],'node_syntax_exit':node_retry['syntax_check']['exit_code']},ensure_ascii=False,indent=2))

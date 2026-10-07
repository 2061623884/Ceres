import hashlib
import json
from pathlib import Path

root = Path.cwd()
audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2-audit'
output = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2'
source = root / 'work/ceres-v4-evaluation/run-04'
ui_path = root / 'work/ceres-v4-evaluation/ui/run-02/result.json'
diag = root / 'work/ceres-v4-evaluation/diagnostics-run03-v3'
run03 = root / 'work/ceres-v4-evaluation/run-03'
probes = [root / 'work/ceres-v4-evaluation/diagnostics-run03', root / 'work/ceres-v4-evaluation/diagnostics-run03-v2']
script = root / 'scripts/eval_v4_record.py'
eval_script = root / 'scripts/eval_v4.py'
prior_map_path = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-audit/input-hashes-before.json'
prior_record_path = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked/acceptance.json'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def files(folder):
    return [p for p in folder.rglob('*') if p.is_file()]

manifest = read(source / 'manifest.json')
parents = []
for item in manifest['schedule']:
    row = read(source / item['execution_id'] / 'result.json')
    parent = row['source_scoring_result']
    path = Path(parent['path']).resolve()
    if sha(path) != parent['sha256']:
        raise SystemExit(f'Parent API source hash mismatch: {path}')
    parents.append(path)
input_files = set(files(source)) | set(files(diag)) | set(files(probes[0])) | set(files(probes[1]))
input_files |= {ui_path, run03 / 'manifest.json', script, eval_script, *parents}
input_files = sorted(p.resolve() for p in input_files)
current = {str(p): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in input_files}
before = read(audit / 'input-hashes-before.json')
after = read(audit / 'input-hashes-after.json')
if len(current) != 477 or before != after or current != after:
    raise SystemExit('The 477 input paths/hashes changed during generation or post-generation audit')

previous = read(prior_map_path)
changed = [p for p in current if p not in previous or current[p] != previous[p]]
removed = [p for p in previous if p not in current]
expected_changed = [str(script.resolve())]
if len(previous) != 477 or changed != expected_changed or removed:
    raise SystemExit(f'Unexpected difference from prior 477-path snapshot: changed={changed}, removed={removed}')

record = read(output / 'acceptance.json')
markdown = (output / 'acceptance.md').read_text(encoding='utf-8')
prior = read(prior_record_path)
summary = read(source / 'summary.json')
diag_manifest = read(diag / 'manifest.json')
ui = read(ui_path)
expected_counts = {'passed': 76, 'failed': 24, 'preparation_failed': 0, 'runner_failed': 0, 'not_executed': 0}
if record['api']['counts'] != expected_counts or record['api']['actual_executions'] != 100:
    raise SystemExit(f'API summary changed: {record["api"]["counts"]}')
if (record['api']['fully_passed'], record['api']['core_pass3']['passed']) != (55, 6):
    raise SystemExit('Business/full/core metrics changed')
hard = record['api']['hard_constraints']
if (hard['all_satisfied'], hard['produced_plan_executions']) != (39, 49):
    raise SystemExit('Hard-constraint metrics changed')
if (record['turns_within_15s'], record['timed_turns'], len(record['failures'])) != (134, 162, 45):
    raise SystemExit('Latency/failure metrics changed')
if record['performance_not_applicable'] != [{'execution_id': 'H20-r1', 'business_status': 'passed'}]:
    raise SystemExit('Performance N/A disclosure changed')
if (record['performance_measured_executions'], record['fully_passed_with_timed_turns']) != (99, 54):
    raise SystemExit('Measured/timed pass counts changed')
if record['automatic_acceptance'] != 'not_passed' or summary['automatic_acceptance'] != 'not_passed':
    raise SystemExit('Unexpected overall acceptance verdict')
if record['api']['manifest'] != str((source / 'manifest.json').resolve()):
    raise SystemExit('API summary manifest is not canonical run-04 manifest')
if diag_manifest['source'] != str(run03.resolve()) or diag_manifest['source_manifest_sha256'] != sha(run03 / 'manifest.json'):
    raise SystemExit('Diagnostic parent is not run-03')
if record['usage']['failed_probe_judge']['calls'] != 2 or len(record['failed_probes']) != 2:
    raise SystemExit('Expected both retained one-call probe records')
if record['reporter_sha256'] != sha(script):
    raise SystemExit('Reporter hash does not match the current reporter source')

# Verify all 100 diagnostic records remain tied to run-03 parent responses.
lineage_count = 0
for item in manifest['schedule']:
    execution_id = item['execution_id']
    api_row = read(source / execution_id / 'result.json')
    parent = api_row['source_scoring_result']
    diagnosed = read(diag / f'{execution_id}.json')
    linked = record['execution_sha256'][execution_id]['diagnostic_source_api']
    if linked != parent or diagnosed['source_result_sha256'] != parent['sha256']:
        raise SystemExit(f'Diagnostic lineage mismatch: {execution_id}')
    parent_path = Path(parent['path']).resolve()
    if not parent_path.is_relative_to(run03.resolve()) or sha(parent_path) != parent['sha256']:
        raise SystemExit(f'Diagnostic parent path/hash mismatch: {execution_id}')
    lineage_count += 1
if lineage_count != 100 or record['diagnostic_verdicts'].get('pass', 0) + record['diagnostic_verdicts'].get('fail', 0) + record['diagnostic_verdicts'].get('unknown', 0) != 100:
    raise SystemExit('Expected 100 diagnosis outputs and lineages')

# The corrected prose is data-derived from the actual retained UI and call records.
ui_count = len(ui['journeys'])
plan_review_count = sum(isinstance(row['additional_plan_assertions'], dict) for row in record['ui_assertion_review'])
for phrase in (f'已记录的{ui_count}条浏览器旅程', f'已记录的成功清单{plan_review_count}份', f'原始裁判捕获调用{record["usage"]["original_judge"]["calls"]}次'):
    if phrase not in markdown:
        raise SystemExit(f'Missing data-derived narrative: {phrase}')
if '两个单条探针均耗尽推理预算' not in markdown or '原始裁判记录保留' in markdown or '下列两条浏览器旅程' in markdown or '专题成功清单' in markdown:
    raise SystemExit('Report narrative does not match the actual retained evidence')
if '记忆样本定义覆盖' not in markdown:
    raise SystemExit('Memory narrative still overstates completion')

for key in ('source_manifest_sha256', 'source_summary_sha256', 'ui_result_sha256', 'diagnostic_manifest_sha256'):
    if record[key] != prior[key]:
        raise SystemExit(f'Prior retained artifact hash changed: {key}')
if record['execution_sha256'] != prior['execution_sha256'] or record['failed_probes'] != prior['failed_probes']:
    raise SystemExit('Execution or probe hashes changed from the prior record')

validation = {
    'report_generation_command_exit_code': int((audit / 'record.exit-code.txt').read_text(encoding='utf-8').strip()),
    'report_generation_stdout': (audit / 'record.stdout.txt').read_text(encoding='utf-8'),
    'report_generation_stderr': (audit / 'record.stderr.txt').read_text(encoding='utf-8'),
    'output': str(output.resolve()),
    'reporter_sha256': record['reporter_sha256'],
    'same_477_paths_as_prior': True,
    'input_hashes_unchanged_during_generation': before == after == current,
    'matched_previous_hashes': len(current) - len(changed),
    'expected_changed_hash': {'path': changed[0], 'prior': previous[changed[0]], 'current': current[changed[0]]},
    'raw_data_inputs_unchanged': True,
    'run04_canonical_api_manifest': record['api']['manifest'],
    'diagnostic_parent': diag_manifest['source'],
    'diagnostic_lineages_verified': lineage_count,
    'markdown_narrative': {'ui_journeys': ui_count, 'offline_checked_success_plans': plan_review_count, 'original_judge_calls': record['usage']['original_judge']['calls'], 'failed_probes': len(record['failed_probes']), 'memory_claim': 'sample definitions and per-execution captured evidence'},
    'metrics': {'business_passed': 76, 'business_failed': 24, 'business_and_applicable_performance_passed': 55, 'core_20_passed': 6, 'hard_constraints': [39, 49], 'turns_within_15s': [134, 162], 'failures': 45, 'performance_not_applicable': ['H20-r1'], 'performance_measured_executions': 99, 'fully_passed_with_timed_turns': 54},
    'current_code_sha256': {'scripts/eval_v4_record.py': sha(script), 'scripts/eval_v4.py': sha(eval_script)},
    'prior_generation_audit_assertion_error_preserved': True,
}
(audit / 'validation-attempt02.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(validation, ensure_ascii=False, indent=2))

import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path.cwd()
audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v3-audit'
output = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v3'
source = root / 'work/ceres-v4-evaluation/run-04'
ui_path = root / 'work/ceres-v4-evaluation/ui/run-02/result.json'
diag = root / 'work/ceres-v4-evaluation/diagnostics-run03-v3'
run03 = root / 'work/ceres-v4-evaluation/run-03'
probes = [root / 'work/ceres-v4-evaluation/diagnostics-run03', root / 'work/ceres-v4-evaluation/diagnostics-run03-v2']
script = root / 'scripts/eval_v4_record.py'
eval_script = root / 'scripts/eval_v4.py'
previous_audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2-audit'
previous_record = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2/acceptance.json'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
if output.exists():
    raise SystemExit(f'Output already exists: {output}')

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def all_files(folder):
    return [path for path in folder.rglob('*') if path.is_file()]

manifest = read(source / 'manifest.json')
parent_files = []
for item in manifest['schedule']:
    row = read(source / item['execution_id'] / 'result.json')
    parent = row['source_scoring_result']
    parent_path = Path(parent['path']).resolve()
    if sha(parent_path) != parent['sha256']:
        raise SystemExit(f'Pre-generation parent source hash mismatch: {parent_path}')
    parent_files.append(parent_path)
input_files = set(all_files(source)) | set(all_files(diag)) | set(all_files(probes[0])) | set(all_files(probes[1]))
input_files |= {ui_path, run03 / 'manifest.json', script, eval_script, *parent_files}
input_files = sorted(path.resolve() for path in input_files)
def hash_map():
    return {str(path): {'bytes': path.stat().st_size, 'sha256': sha(path)} for path in input_files if path.is_file()}

before = hash_map()
if len(before) != 477:
    raise SystemExit(f'Expected 477 input paths; found {len(before)}')
(audit / 'input-hashes-before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
args = [python, '-X', 'utf8', 'scripts/eval_v4_record.py',
        '--source', 'work/ceres-v4-evaluation/run-04',
        '--ui', 'work/ceres-v4-evaluation/ui/run-02/result.json',
        '--diagnostics', 'work/ceres-v4-evaluation/diagnostics-run03-v3',
        '--probe', 'work/ceres-v4-evaluation/diagnostics-run03',
        '--probe', 'work/ceres-v4-evaluation/diagnostics-run03-v2',
        '--output', 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v3']
(audit / 'record.command.txt').write_text(subprocess.list2cmdline(args) + '\n', encoding='utf-8')
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
proc = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(audit / 'record.stdout.txt').write_bytes(proc.stdout)
(audit / 'record.stderr.txt').write_bytes(proc.stderr)
(audit / 'record.exit-code.txt').write_text(str(proc.returncode) + '\n', encoding='utf-8')
if proc.returncode != 0:
    raise SystemExit(f'Record generation failed with exit {proc.returncode}')
after = hash_map()
(audit / 'input-hashes-after.json').write_text(json.dumps(after, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
if before != after:
    raise SystemExit('Input hashes changed during record generation')

record = read(output / 'acceptance.json')
markdown = (output / 'acceptance.md').read_text(encoding='utf-8')
previous_map = read(previous_audit / 'input-hashes-before.json')
previous = read(previous_record)
summary = read(source / 'summary.json')
diag_manifest = read(diag / 'manifest.json')
ui = read(ui_path)
changed = [path for path in before if path not in previous_map or before[path] != previous_map[path]]
removed = [path for path in previous_map if path not in before]
if len(previous_map) != 477 or changed != [str(script.resolve())] or removed:
    raise SystemExit(f'Unexpected prior input-map difference: changed={changed}, removed={removed}')
expected_counts = {'passed': 76, 'failed': 24, 'preparation_failed': 0, 'runner_failed': 0, 'not_executed': 0}
if record['api']['counts'] != expected_counts or record['api']['actual_executions'] != 100:
    raise SystemExit('API results differ from retained run-04')
if (record['api']['fully_passed'], record['api']['core_pass3']['passed']) != (55, 6):
    raise SystemExit('Business/full/core metrics changed')
hard = record['api']['hard_constraints']
if (hard['all_satisfied'], hard['produced_plan_executions']) != (39, 49):
    raise SystemExit('Hard-constraint metrics changed')
if (record['turns_within_15s'], record['timed_turns'], len(record['failures'])) != (134, 162, 45):
    raise SystemExit('Latency/failure metrics changed')
if record['performance_not_applicable'] != [{'execution_id': 'H20-r1', 'business_status': 'passed'}]:
    raise SystemExit('N/A performance set changed')
if (record['performance_measured_executions'], record['fully_passed_with_timed_turns']) != (99, 54):
    raise SystemExit('Measured performance counts changed')
if record['automatic_acceptance'] != 'not_passed' or summary['automatic_acceptance'] != 'not_passed':
    raise SystemExit('Unexpected acceptance gate')
if record['api']['manifest'] != str((source / 'manifest.json').resolve()):
    raise SystemExit('API manifest pointer is not canonical run-04')
if diag_manifest['source'] != str(run03.resolve()) or diag_manifest['source_manifest_sha256'] != sha(run03 / 'manifest.json'):
    raise SystemExit('Diagnostic parent does not point to run-03')
if record['reporter_sha256'] != sha(script):
    raise SystemExit('Reporter SHA mismatch')
if record['usage']['failed_probe_judge']['calls'] != 2 or len(record['failed_probes']) != 2:
    raise SystemExit('Expected two retained failed probes')

lineage_count = 0
for item in manifest['schedule']:
    execution_id = item['execution_id']
    source_row = read(source / execution_id / 'result.json')
    parent = source_row['source_scoring_result']
    diagnosis = read(diag / f'{execution_id}.json')
    linked = record['execution_sha256'][execution_id]['diagnostic_source_api']
    parent_path = Path(parent['path']).resolve()
    if linked != parent or diagnosis['source_result_sha256'] != parent['sha256']:
        raise SystemExit(f'Diagnostic lineage mismatch: {execution_id}')
    if not parent_path.is_relative_to(run03.resolve()) or sha(parent_path) != parent['sha256']:
        raise SystemExit(f'Run-03 source path/hash mismatch: {execution_id}')
    lineage_count += 1
if lineage_count != 100:
    raise SystemExit(f'Expected 100 diagnostic lineages; got {lineage_count}')

# Verify transport timeouts are represented by captured request/error without claiming a response exists.
diag_rows = [read(path) for path in diag.glob('*.json') if path.name not in ('manifest.json', 'summary.json')]
timeouts = [row for row in diag_rows if row.get('error', {}).get('type') == 'ReadTimeout']
if len(timeouts) != 9 or not all(len(row['calls']) == 1 and row['calls'][0].get('request') and not row['calls'][0].get('response_status') and not row['calls'][0].get('response_choices') for row in timeouts):
    raise SystemExit('Nine ReadTimeout entries are not request/error-only as expected')
ui_count = len(ui['journeys'])
plan_review_count = sum(isinstance(row['additional_plan_assertions'], dict) for row in record['ui_assertion_review'])
expected_phrases = (
    f'已记录的{ui_count}条浏览器旅程',
    'UI输入文件路径和摘要见机器记录',
    f'已记录的成功清单{plan_review_count}份',
    '逐条保留可取得的请求、响应或错误',
    '存在可重放输入时使用原始捕获提示',
    f'原始裁判捕获调用{record["usage"]["original_judge"]["calls"]}次',
    '记忆样本定义覆盖',
)
for phrase in expected_phrases:
    if phrase not in markdown:
        raise SystemExit(f'Markdown missing evidence-bound narrative: {phrase}')
unsupported_phrases = ('下列两条浏览器旅程', '专题成功清单', '本次探针', '原始裁判记录保留',
                       'UI运行条件与身份见原始UI回执', '诊断保留原始捕获提示', '保存实际序列化请求与响应')
if any(phrase in markdown for phrase in unsupported_phrases):
    raise SystemExit('Markdown still contains unsupported narrative')
for key in ('source_manifest_sha256', 'source_summary_sha256', 'ui_result_sha256', 'diagnostic_manifest_sha256'):
    if record[key] != previous[key]:
        raise SystemExit(f'Artifact hash differs from previous reviewed report: {key}')
if record['execution_sha256'] != previous['execution_sha256'] or record['failed_probes'] != previous['failed_probes']:
    raise SystemExit('Execution or probe hashes differ from previous reviewed report')

validation = {
    'record_command_exit_code': proc.returncode,
    'record_command_stdout': proc.stdout.decode('utf-8', errors='replace'),
    'record_command_stderr': proc.stderr.decode('utf-8', errors='replace'),
    'output': str(output.resolve()),
    'reporter_sha256': record['reporter_sha256'],
    '477_input_paths_unchanged_during_generation': before == after,
    'same_477_paths_as_v2': True,
    'hashes_matching_v2': len(before) - len(changed),
    'expected_reporter_hash_change': {'path': changed[0], 'prior': previous_map[changed[0]], 'current': before[changed[0]]},
    'raw_data_inputs_unchanged': True,
    'run04_canonical_api_manifest': record['api']['manifest'],
    'diagnostic_parent_source': diag_manifest['source'],
    'diagnostic_lineages_verified': lineage_count,
    'timeout_without_response_count': len(timeouts),
    'markdown_counts': {'ui_journeys': ui_count, 'offline_success_plan_reviews': plan_review_count, 'original_judge_calls': record['usage']['original_judge']['calls'], 'probe_calls': record['usage']['failed_probe_judge']['calls'], 'timeout_calls_without_response': len(timeouts)},
    'metrics': {'passed_failed': [76, 24], 'business_and_applicable_performance_passed': 55, 'core_passed': 6, 'hard_constraints': [39, 49], 'turns_within_15s': [134, 162], 'failures': 45, 'performance_not_applicable': ['H20-r1'], 'performance_measured': 99, 'fully_passed_with_timed_turns': 54},
}
(audit / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(validation, ensure_ascii=False, indent=2))

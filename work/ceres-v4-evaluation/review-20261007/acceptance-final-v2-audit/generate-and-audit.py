import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path.cwd()
audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2-audit'
output = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2'
source = root / 'work/ceres-v4-evaluation/run-04'
ui = root / 'work/ceres-v4-evaluation/ui/run-02/result.json'
diagnostics = root / 'work/ceres-v4-evaluation/diagnostics-run03-v3'
run03 = root / 'work/ceres-v4-evaluation/run-03'
probes = [root / 'work/ceres-v4-evaluation/diagnostics-run03', root / 'work/ceres-v4-evaluation/diagnostics-run03-v2']
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
script = root / 'scripts/eval_v4_record.py'
eval_script = root / 'scripts/eval_v4.py'
prior_audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-audit'
prior_report = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked/acceptance.json'
if output.exists():
    raise SystemExit(f'Output already exists: {output}')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def all_files(folder):
    return [path for path in folder.rglob('*') if path.is_file()]

source_manifest = read(source / 'manifest.json')
parent_source_files = []
for item in source_manifest['schedule']:
    row = read(source / item['execution_id'] / 'result.json')
    parent = row['source_scoring_result']
    parent_path = Path(parent['path']).resolve()
    if sha(parent_path) != parent['sha256']:
        raise SystemExit(f'Pre-generation parent source hash mismatch: {parent_path}')
    parent_source_files.append(parent_path)
inputs = set(all_files(source)) | set(all_files(diagnostics)) | set(all_files(probes[0])) | set(all_files(probes[1]))
inputs |= {ui, run03 / 'manifest.json', script, eval_script, *parent_source_files}
inputs = sorted(path.resolve() for path in inputs)
def hash_map():
    result = {}
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
        result[str(path)] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result

before = hash_map()
(audit / 'input-hashes-before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
args = [python, '-X', 'utf8', 'scripts/eval_v4_record.py',
        '--source', 'work/ceres-v4-evaluation/run-04',
        '--ui', 'work/ceres-v4-evaluation/ui/run-02/result.json',
        '--diagnostics', 'work/ceres-v4-evaluation/diagnostics-run03-v3',
        '--probe', 'work/ceres-v4-evaluation/diagnostics-run03',
        '--probe', 'work/ceres-v4-evaluation/diagnostics-run03-v2',
        '--output', 'work/ceres-v4-evaluation/review-20261007/acceptance-final-v2']
(audit / 'record.command.txt').write_text(subprocess.list2cmdline(args) + '\n', encoding='utf-8')
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
process = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(audit / 'record.stdout.txt').write_bytes(process.stdout)
(audit / 'record.stderr.txt').write_bytes(process.stderr)
(audit / 'record.exit-code.txt').write_text(str(process.returncode) + '\n', encoding='utf-8')
if process.returncode != 0:
    raise SystemExit(f'Record generation failed with exit {process.returncode}')
after = hash_map()
(audit / 'input-hashes-after.json').write_text(json.dumps(after, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
if before != after:
    raise SystemExit('One or more current inputs changed during generation')

record = read(output / 'acceptance.json')
markdown = (output / 'acceptance.md').read_text(encoding='utf-8')
summary = read(source / 'summary.json')
prior = read(prior_report)
diag_manifest = read(diagnostics / 'manifest.json')
previous_map = read(prior_audit / 'input-hashes-before.json')
changed_from_prior = [path for path in before if path not in previous_map or before[path] != previous_map[path]]
removed_from_prior = [path for path in previous_map if path not in before]
expected_changed = [str(script.resolve())]
if len(before) != 477 or len(previous_map) != 477 or changed_from_prior != expected_changed or removed_from_prior:
    raise SystemExit(f'Input-set drift unexpected: count={len(before)}, changed={changed_from_prior}, removed={removed_from_prior}')

expected_counts = {'passed': 76, 'failed': 24, 'preparation_failed': 0, 'runner_failed': 0, 'not_executed': 0}
if record['api']['counts'] != expected_counts or record['api']['actual_executions'] != 100:
    raise SystemExit(f'API counts changed: {record["api"]["counts"]}')
if record['api']['fully_passed'] != 55 or record['api']['core_pass3']['passed'] != 6:
    raise SystemExit('Business/full/core pass metrics changed')
hard = record['api']['hard_constraints']
if (hard['all_satisfied'], hard['produced_plan_executions']) != (39, 49):
    raise SystemExit(f'Hard constraint metrics changed: {hard}')
if (record['turns_within_15s'], record['timed_turns'], len(record['failures'])) != (134, 162, 45):
    raise SystemExit('Latency or failure count changed')
if record['performance_not_applicable'] != [{'execution_id': 'H20-r1', 'business_status': 'passed'}]:
    raise SystemExit(f'Performance N/A set changed: {record["performance_not_applicable"]}')
if (record['performance_measured_executions'], record['fully_passed_with_timed_turns']) != (99, 54):
    raise SystemExit('Measured/timed full-pass counts changed')
if record['api']['manifest'] != str((source / 'manifest.json').resolve()):
    raise SystemExit(f'API summary manifest does not point to run-04: {record["api"]["manifest"]}')
if diag_manifest['source'] != str(run03.resolve()) or diag_manifest['source_manifest_sha256'] != sha(run03 / 'manifest.json'):
    raise SystemExit('Diagnostic parent source is not the retained run-03 manifest')
if record['usage']['failed_probe_judge']['calls'] != 2:
    raise SystemExit('Expected exactly the two retained failed probes')
if record['reporter_sha256'] != sha(script):
    raise SystemExit('Acceptance reporter source hash does not match the current source')

for key in ('source_manifest_sha256', 'source_summary_sha256', 'ui_result_sha256', 'diagnostic_manifest_sha256'):
    if record[key] != prior[key]:
        raise SystemExit(f'Prior report input hash changed: {key}')
if record['execution_sha256'] != prior['execution_sha256'] or record['failed_probes'] != prior['failed_probes']:
    raise SystemExit('API/diagnostic execution or probe hashes changed from the prior report')
if record['source_manifest_sha256'] != sha(source / 'manifest.json') or record['source_summary_sha256'] != sha(source / 'summary.json'):
    raise SystemExit('Run-04 manifest/summary source hash mismatch')
if record['ui_result_sha256'] != sha(ui) or record['diagnostic_manifest_sha256'] != sha(diagnostics / 'manifest.json'):
    raise SystemExit('UI/diagnostic manifest source hash mismatch')

ui_count = len(read(ui)['journeys'])
plan_review_count = sum(isinstance(row['additional_plan_assertions'], dict) for row in record['ui_assertion_review'])
for phrase in (f'已记录的{ui_count}条浏览器旅程', f'已记录的成功清单{plan_review_count}份', f'原始裁判捕获调用{record["usage"]["original_judge"]["calls"]}次'):
    if phrase not in markdown:
        raise SystemExit(f'Markdown lacks data-derived statement: {phrase}')
if '本次未提供参数探针，未计入调用。' not in markdown or '两个单条探针均耗尽' in markdown:
    raise SystemExit('Probe narrative does not match supplied evidence')
if '记忆样本定义覆盖' not in markdown or '全部完成' in markdown:
    raise SystemExit('Memory narrative overstates the captured evidence')

validation = {
    'generation_exit_code': process.returncode,
    'output': str(output.resolve()),
    'reporter_sha256': record['reporter_sha256'],
    'current_input_count': len(before),
    'current_input_hashes_unchanged_during_generation': before == after,
    'prior_input_set_count': len(previous_map),
    'unchanged_from_prior_input_sha_count': len(before) - len(changed_from_prior),
    'expected_source_change_from_prior': {'path': str(script.resolve()), 'prior_sha256': previous_map[str(script.resolve())]['sha256'], 'current_sha256': before[str(script.resolve())]['sha256']},
    'no_input_paths_added_or_removed': not removed_from_prior and len(before) == len(previous_map),
    'previous_reviewed_artifact_hashes_unchanged': True,
    'api_manifest_points_to_run04': record['api']['manifest'],
    'diagnostics_parent_points_to_run03': diag_manifest['source'],
    'markdown_narrative_counts': {'ui_journeys': ui_count, 'successful_plan_reviews': plan_review_count, 'original_judge_calls': record['usage']['original_judge']['calls']},
    'metrics': {
        'passed_failed': [record['api']['counts']['passed'], record['api']['counts']['failed']],
        'business_and_applicable_performance_passed': record['api']['fully_passed'],
        'core_20_passed': record['api']['core_pass3']['passed'],
        'hard_constraints': [hard['all_satisfied'], hard['produced_plan_executions']],
        'turns_within_15s': [record['turns_within_15s'], record['timed_turns']],
        'failures': len(record['failures']),
        'performance_not_applicable': record['performance_not_applicable'],
        'performance_measured_executions': record['performance_measured_executions'],
        'fully_passed_with_timed_turns': record['fully_passed_with_timed_turns'],
        'failed_probe_calls': record['usage']['failed_probe_judge']['calls'],
    },
    'current_sources': {'scripts/eval_v4_record.py': sha(script), 'scripts/eval_v4.py': sha(eval_script)},
}
(audit / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'command': args, 'exit_code': process.returncode,
                  'stdout': process.stdout.decode('utf-8', errors='replace'),
                  'stderr': process.stderr.decode('utf-8', errors='replace'), 'validation': validation}, ensure_ascii=False, indent=2))

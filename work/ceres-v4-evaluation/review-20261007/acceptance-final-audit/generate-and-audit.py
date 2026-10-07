import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
audit = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final-audit'
output = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-final'
source = root / 'work/ceres-v4-evaluation/run-04'
ui = root / 'work/ceres-v4-evaluation/ui/run-02/result.json'
diagnostics = root / 'work/ceres-v4-evaluation/diagnostics-run03-v3'
run03 = root / 'work/ceres-v4-evaluation/run-03'
probes = [root / 'work/ceres-v4-evaluation/diagnostics-run03', root / 'work/ceres-v4-evaluation/diagnostics-run03-v2']
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
script = root / 'scripts/eval_v4_record.py'
eval_script = root / 'scripts/eval_v4.py'

if output.exists():
    raise SystemExit(f'Output already exists: {output}')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def json_read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def all_files(folder):
    return [path for path in folder.rglob('*') if path.is_file()]

source_manifest = json_read(source / 'manifest.json')
parent_source_files = []
for item in source_manifest['schedule']:
    row = json_read(source / item['execution_id'] / 'result.json')
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
        '--output', 'work/ceres-v4-evaluation/review-20261007/acceptance-final']
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
    raise SystemExit('One or more source inputs changed during generation')

record = json_read(output / 'acceptance.json')
summary = json_read(source / 'summary.json')
prior_path = root / 'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked/acceptance.json'
prior = json_read(prior_path)
diag_manifest = json_read(diagnostics / 'manifest.json')

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

# Confirm the output points to these exact inputs and matches the previously reviewed report's retained input hashes.
input_sha_keys = ('source_manifest_sha256', 'source_summary_sha256', 'ui_result_sha256', 'diagnostic_manifest_sha256')
for key in input_sha_keys:
    if record[key] != prior[key]:
        raise SystemExit(f'Prior input hash changed: {key}')
if record['execution_sha256'] != prior['execution_sha256'] or record['failed_probes'] != prior['failed_probes']:
    raise SystemExit('API/diagnostic execution or probe hashes changed from the prior reviewed record')
if record['source_manifest_sha256'] != sha(source / 'manifest.json') or record['source_summary_sha256'] != sha(source / 'summary.json'):
    raise SystemExit('Run-04 manifest/summary source hash mismatch')
if record['ui_result_sha256'] != sha(ui) or record['diagnostic_manifest_sha256'] != sha(diagnostics / 'manifest.json'):
    raise SystemExit('UI/diagnostic manifest source hash mismatch')

validation = {
    'generation_exit_code': process.returncode,
    'output': str(output.resolve()),
    'reporter_sha256': record['reporter_sha256'],
    'source_hash_map_unchanged': before == after,
    'source_file_count_hashed': len(before),
    'previous_reviewed_input_hashes_unchanged': True,
    'api_manifest_points_to_run04': record['api']['manifest'],
    'diagnostics_parent_points_to_run03': diag_manifest['source'],
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
    'prior_reporter_sha256': prior['reporter_sha256'],
}
(audit / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'record_command': args, 'exit_code': process.returncode,
                  'stdout': process.stdout.decode('utf-8', errors='replace'),
                  'stderr': process.stderr.decode('utf-8', errors='replace'), 'validation': validation}, ensure_ascii=False, indent=2))

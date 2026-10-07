import hashlib
import json
import os
from pathlib import Path
import subprocess

repo = Path.cwd()
out = repo / 'work/ceres-v4-evaluation/review-20261007/red-failure-pipeline/red-old-record-with-probes-attempt02'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
runner = out / 'run-red-test-with-probes.py'
args = [python, '-X', 'utf8', str(runner)]
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
command = subprocess.list2cmdline(args)
(out / 'test.command.txt').write_text(command + '\n', encoding='utf-8')
proc = subprocess.run(args, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(out / 'test.stdout.txt').write_bytes(proc.stdout)
(out / 'test.stderr.txt').write_bytes(proc.stderr)
(out / 'test.exit-code.txt').write_text(str(proc.returncode) + '\n', encoding='utf-8')
version = subprocess.run([python, '--version'], cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
old_manifest = json.loads((repo / 'work/ceres-v4-evaluation/review-20261007/red-failure-pipeline/frozen-old/freeze-manifest.json').read_text(encoding='utf-8'))
record_sha = next(item['sha256'] for item in old_manifest['modules'] if item['path'] == 'scripts/eval_v4_record.py')
test_path = repo / 'scripts/test_eval_v4_record.py'
metadata = {
    'python_executable': python, 'python_version': (version.stdout or version.stderr).decode('utf-8', errors='replace').strip(),
    'cwd': str(repo), 'binding': 'old recorder from frozen HEAD; current judge remains bound',
    'adapter_only_change': 'wrapper appends two existing required --probe paths to old recorder argv',
    'probe_paths': [str(p) for p in (repo / 'work/ceres-v4-evaluation/diagnostics-run03', repo / 'work/ceres-v4-evaluation/diagnostics-run03-v2')],
    'old_recorder_sha256': record_sha, 'test_sha256': hashlib.sha256(test_path.read_bytes()).hexdigest(), 'exit_code': proc.returncode,
}
(out / 'environment.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'command': command, 'exit_code': proc.returncode, 'stdout': proc.stdout.decode('utf-8', errors='replace'),
                  'stderr': proc.stderr.decode('utf-8', errors='replace'), 'metadata': metadata}, ensure_ascii=False, indent=2))

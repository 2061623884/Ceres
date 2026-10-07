import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path.cwd()
out = root / 'work/ceres-v4-evaluation/review-20261007/red-narrative'
reporter = root / 'scripts/eval_v4_record.py'
test_file = root / 'scripts/test_eval_v4_record.py'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

frozen = out / 'eval_v4_record.py'
frozen.write_bytes(reporter.read_bytes())
reporter_sha = sha(reporter)
if sha(frozen) != reporter_sha:
    raise SystemExit('Frozen reporter bytes do not match current source')

args = [python, '-X', 'utf8', '-m', 'unittest',
        'test_eval_v4_record.AcceptanceTests.test_incomplete_batch_reaches_acceptance_without_model_calls', '-v']
command = subprocess.list2cmdline(args)
(out / 'red-narrative.command.txt').write_text(command + '\n', encoding='utf-8')
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
proc = subprocess.run(args, cwd=root / 'scripts', env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(out / 'red-narrative.stdout.txt').write_bytes(proc.stdout)
(out / 'red-narrative.stderr.txt').write_bytes(proc.stderr)
(out / 'red-narrative.exit-code.txt').write_text(str(proc.returncode) + '\n', encoding='utf-8')
version = subprocess.run([python, '--version'], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
metadata = {
    'python_executable': python,
    'python_version': (version.stdout or version.stderr).decode('utf-8', errors='replace').strip(),
    'cwd': str(root / 'scripts'),
    'test': 'test_eval_v4_record.AcceptanceTests.test_incomplete_batch_reaches_acceptance_without_model_calls',
    'reporter_snapshot': str(frozen.resolve()),
    'reporter_sha256': reporter_sha,
    'test_module_sha256': sha(test_file),
    'exit_code': proc.returncode,
    'network_and_product_load_are_mocked_by_test': True,
}
if sha(reporter) != reporter_sha:
    raise SystemExit('Reporter source changed during test')
(out / 'environment.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'command': command, 'exit_code': proc.returncode,
                  'stdout': proc.stdout.decode('utf-8', errors='replace'),
                  'stderr': proc.stderr.decode('utf-8', errors='replace'), 'metadata': metadata}, ensure_ascii=False, indent=2))

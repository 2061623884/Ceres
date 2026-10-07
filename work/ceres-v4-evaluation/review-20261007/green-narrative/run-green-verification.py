import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path.cwd()
out = root / 'work/ceres-v4-evaluation/review-20261007/green-narrative'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
commands = {
    'unit-tests': [python, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_eval_v4*.py', '-v'],
    'python-compile': [python, '-X', 'utf8', str(out / 'compile-eval-modules.py')],
}
for label, args in commands.items():
    (out / f'{label}.command.txt').write_text(subprocess.list2cmdline(args) + '\n', encoding='utf-8')
    proc = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out / f'{label}.stdout.txt').write_bytes(proc.stdout)
    (out / f'{label}.stderr.txt').write_bytes(proc.stderr)
    (out / f'{label}.exit-code.txt').write_text(str(proc.returncode) + '\n', encoding='utf-8')
    print(json.dumps({'label': label, 'command': args, 'exit_code': proc.returncode,
                      'stdout': proc.stdout.decode('utf-8', errors='replace'),
                      'stderr': proc.stderr.decode('utf-8', errors='replace')}, ensure_ascii=False))

version = subprocess.run([python, '--version'], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
files = sorted([*Path('scripts').glob('eval_v4*.py'), *Path('scripts').glob('test_eval_v4*.py')])
env_receipt = {
    'python_executable': python,
    'python_version': (version.stdout or version.stderr).decode('utf-8', errors='replace').strip(),
    'cwd': str(root),
    'test_bytecode_writes_disabled': True,
    'test_discovery_pattern': 'test_eval_v4*.py',
    'compile_method': 'compile(file_bytes, path, "exec"), no bytecode files written',
    'source_files': [{'path': path.as_posix(), 'bytes': path.stat().st_size,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
}
(out / 'environment.json').write_text(json.dumps(env_receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

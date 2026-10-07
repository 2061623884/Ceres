import json
import os
from pathlib import Path
import subprocess

repo = Path.cwd()
base = repo / 'work/ceres-v4-evaluation/review-20261007/red-failure-pipeline'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
runner = base / 'run-red-test.py'
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
for binding in ('judge', 'record'):
    out = base / ('red-old-' + binding)
    out.mkdir(exist_ok=True)
    if any(out.iterdir()):
        raise SystemExit(f'Output directory is not empty: {out}')
    args = [python, '-X', 'utf8', str(runner), '--binding', binding]
    command = subprocess.list2cmdline(args)
    (out / 'test.command.txt').write_text(command + '\n', encoding='utf-8')
    process = subprocess.run(args, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out / 'test.stdout.txt').write_bytes(process.stdout)
    (out / 'test.stderr.txt').write_bytes(process.stderr)
    (out / 'test.exit-code.txt').write_text(str(process.returncode) + '\n', encoding='utf-8')
    print(json.dumps({'binding': binding, 'command': command, 'exit_code': process.returncode,
                      'stdout': process.stdout.decode('utf-8', errors='replace'),
                      'stderr': process.stderr.decode('utf-8', errors='replace')}, ensure_ascii=False))

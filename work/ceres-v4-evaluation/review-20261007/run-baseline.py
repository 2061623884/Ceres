import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
out = root / 'work/ceres-v4-evaluation/review-20261007'
python = r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
node = r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
compile_code = "from pathlib import Path; files=['scripts/eval_v4.py','scripts/eval_v4_judge.py','scripts/eval_v4_record.py','scripts/test_eval_v4.py']; [compile(Path(name).read_bytes(), name, 'exec') for name in files]; print('compiled: ' + ', '.join(files))"
commands = [
    ('scorer-unittest', [python, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_eval_v4.py', '-v'], True),
    ('python-compile', [python, '-X', 'utf8', '-c', compile_code], False),
    ('ui-node-check', [node, '--check', 'scripts/eval_v4_ui.mjs'], False),
]
def run(args, env=None):
    p = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p

def record_command(name, args, env=None):
    p = run(args, env)
    (out / f'{name}.stdout.txt').write_bytes(p.stdout)
    (out / f'{name}.stderr.txt').write_bytes(p.stderr)
    (out / f'{name}.exit-code.txt').write_text(str(p.returncode) + '\n', encoding='utf-8')
    (out / f'{name}.command.txt').write_text(subprocess.list2cmdline(args) + '\n', encoding='utf-8')
    return {'name': name, 'command': args, 'exit_code': p.returncode,
            'stdout_bytes': len(p.stdout), 'stderr_bytes': len(p.stderr),
            'stdout_sha256': hashlib.sha256(p.stdout).hexdigest(),
            'stderr_sha256': hashlib.sha256(p.stderr).hexdigest()}

def git(args):
    p = subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {'command': ['git', *args], 'exit_code': p.returncode,
            'stdout': p.stdout.decode('utf-8', errors='replace'),
            'stderr': p.stderr.decode('utf-8', errors='replace'),
            'stdout_sha256': hashlib.sha256(p.stdout).hexdigest(),
            'stderr_sha256': hashlib.sha256(p.stderr).hexdigest()}

before = {
    'head': git(['rev-parse', 'HEAD']),
    'branch': git(['branch', '--show-current']),
    'base': git(['rev-parse', 'ee7ce10']),
    'status': git(['status', '--short']),
    'index_paths': git(['diff', '--cached', '--name-only', '-z']),
}
env_capture = {
    'python_executable': python,
    'python_version': run([python, '--version']).stdout.decode('utf-8', errors='replace').strip(),
    'python_runtime_executable': sys.executable,
    'node_executable': node,
    'node_version': run([node, '--version']).stdout.decode('utf-8', errors='replace').strip(),
    'head_expected': 'abd61394437f21c1b474d39c56559a245dc21e97',
    'base_expected': 'ee7ce104885f731bc48bc8c6338c00d802ba0619',
    'test_bytecode_writes_disabled': True,
    'compile_check_writes_no_bytecode': True,
}
(out / 'environment.json').write_text(json.dumps(env_capture, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
results = []
for name, args, disable_bytecode in commands:
    env = os.environ.copy()
    if disable_bytecode:
        env['PYTHONDONTWRITEBYTECODE'] = '1'
    results.append(record_command(name, args, env))
after = {
    'head': git(['rev-parse', 'HEAD']),
    'branch': git(['branch', '--show-current']),
    'status': git(['status', '--short']),
    'index_paths': git(['diff', '--cached', '--name-only', '-z']),
}
receipt = {
    'baseline': '10 scorer unit tests, Python source compilation, UI runner node --check',
    'environment': env_capture,
    'before': before,
    'commands': results,
    'after': after,
    'head_is_expected': before['head']['stdout'].strip() == env_capture['head_expected'] == after['head']['stdout'].strip(),
    'base_is_expected': before['base']['stdout'].strip() == env_capture['base_expected'],
    'branch_unchanged': before['branch']['stdout'] == after['branch']['stdout'],
    'index_unchanged': before['index_paths']['stdout'] == after['index_paths']['stdout'],
    'working_status_unchanged_at_directory_granularity': before['status']['stdout'] == after['status']['stdout'],
    'all_checks_exit_zero': all(x['exit_code'] == 0 for x in results),
}
(out / 'baseline-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'receipt': str(out / 'baseline-receipt.json'), 'head_is_expected': receipt['head_is_expected'],
                  'base_is_expected': receipt['base_is_expected'], 'all_checks_exit_zero': receipt['all_checks_exit_zero'],
                  'commands': results, 'index_unchanged': receipt['index_unchanged'],
                  'working_status_unchanged_at_directory_granularity': receipt['working_status_unchanged_at_directory_granularity']}, ensure_ascii=False, indent=2))
import json, subprocess
from pathlib import Path
root = Path.cwd(); pre = root / 'work/ceres-v4-evaluation/evidence/precommit'
audit = json.loads((pre / 'precommit-audit.stdout.json').read_text(encoding='utf-8'))
out = audit['git_diff_cached_check']['stdout']
markers = ['new blank line at EOF', 'trailing whitespace.', 'space before tab in indent.']
counts = {marker: out.count(marker) for marker in markers}
path = 'work/ceres-v4-evaluation/ui/run-02-service-verify-attempt01.stderr.txt'
p = subprocess.run(['git','show',f':{path}'], cwd=root, stdout=subprocess.PIPE, check=True)
lines = p.stdout.splitlines(keepends=True)
line9 = lines[8]
result = {'git_diff_check_message_counts': counts, 'raw_stderr_path': path, 'raw_stderr_index_line_9_repr': repr(line9), 'raw_stderr_index_line_9_hex': line9.hex(), 'staged_paths_filename': 'work/ceres-v4-evaluation/evidence/precommit/diff-check-affected-files.txt', 'all_affected_paths_under_work': not any(not line.startswith('work/ceres-v4-evaluation/') for line in (pre / 'diff-check-affected-files.txt').read_text(encoding='utf-8').splitlines())}
(pre / 'diff-check-details.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
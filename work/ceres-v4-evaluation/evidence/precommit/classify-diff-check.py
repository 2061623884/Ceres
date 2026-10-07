import json
import subprocess
from collections import Counter
from pathlib import Path
root = Path.cwd()
pre = root / 'work/ceres-v4-evaluation/evidence/precommit'
audit = json.loads((pre / 'precommit-audit.stdout.json').read_text(encoding='utf-8'))
files = []
for line in audit['git_diff_cached_check']['stdout'].splitlines():
    marker = ': trailing whitespace.'
    if marker in line:
        files.append(line.split(marker, 1)[0].rsplit(':', 1)[0])
unique = sorted(set(files))
(pre / 'diff-check-affected-files.txt').write_text(''.join(path + '\n' for path in unique), encoding='utf-8')
by_root = Counter(path.split('/', 1)[0] for path in unique)
by_area = Counter('/'.join(path.split('/')[:3]) if len(path.split('/')) >= 3 else path for path in unique)
outside_work = [path for path in unique if not path.startswith('work/ceres-v4-evaluation/')]
line_stats = Counter()
non_eol_trailing = []
for i, path in enumerate(unique, 1):
    p = subprocess.run(['git', 'show', f':{path}'], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f'git show index failed for {path}: {p.stderr.decode(errors="replace")}')
    data = p.stdout
    lines = data.splitlines(keepends=True)
    crlf_lines = sum(line.endswith(b'\r\n') for line in lines)
    lf_lines = sum(line.endswith(b'\n') and not line.endswith(b'\r\n') for line in lines)
    bare_cr_lines = sum(line.endswith(b'\r') for line in lines)
    extra = [n for n, line in enumerate(lines, 1) if line.endswith((b' \r\n', b'\t\r\n', b' \n', b'\t\n', b' ', b'\t'))]
    if extra:
        non_eol_trailing.append({'path': path, 'line_numbers': extra[:20], 'count': len(extra)})
    line_stats[f'crlf:{crlf_lines > 0}'] += 1
    line_stats[f'lf:{lf_lines > 0}'] += 1
    if bare_cr_lines:
        line_stats['bare_cr_files'] += 1
    if crlf_lines and not lf_lines and not extra:
        line_stats['crlf_only_no_space_tab_trailing'] += 1
    elif not extra:
        line_stats['no_space_tab_trailing_other_line_endings'] += 1
    if i % 200 == 0:
        pass
result = {
    'affected_file_count': len(unique),
    'affected_report_entries': len(files),
    'affected_paths_by_top_level': dict(sorted(by_root.items())),
    'affected_paths_by_area': dict(sorted(by_area.items())),
    'outside_work_evidence_paths': outside_work,
    'indexed_line_ending_checks': dict(sorted(line_stats.items())),
    'files_with_space_or_tab_before_line_ending': non_eol_trailing,
    'affected_path_list': 'work/ceres-v4-evaluation/evidence/precommit/diff-check-affected-files.txt',
}
(pre / 'diff-check-classification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
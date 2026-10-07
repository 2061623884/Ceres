import json
import re
from collections import Counter
from pathlib import Path
root = Path.cwd()
pre = root / 'work/ceres-v4-evaluation/evidence/precommit'
audit = json.loads((pre / 'precommit-audit.stdout.json').read_text(encoding='utf-8'))
check = audit['git_diff_cached_check']
files = Counter()
first_lines = {}
for line in check['stdout'].splitlines():
    match = re.match(r'^(.*?):([0-9]+): trailing whitespace\.$', line)
    if match:
        path, line_number = match.group(1), int(match.group(2))
        files[path] += 1
        first_lines.setdefault(path, line_number)
result = {
    'audit_overall_pass': audit['overall_pass'],
    'git_diff_cached_check_exit': check['exit_code'],
    'trailing_whitespace_reported_line_count': sum(files.values()),
    'affected_file_count': len(files),
    'affected_files': [{'path': path, 'reported_lines': count, 'first_reported_line': first_lines[path]} for path, count in sorted(files.items())],
    'other_gates': {
        'unexpected_paths': audit['allowed_scope']['unexpected_paths'],
        'missing_required_exact_paths': audit['allowed_scope']['missing_required_exact_paths'],
        'forbidden_secret_db_cache_paths': audit['allowed_scope']['forbidden_secret_db_cache_paths'],
        'readme_cached_one_plus_unstaged_seven': audit['README']['cached_one_line_only_and_original_seven_unstaged'],
        'candidate': audit['candidate'],
        'hash_gates': audit['hash_gates'],
        'lfs_assets_all_index_pointers_with_lfs_filter': audit['lfs_assets_all_index_pointers_with_lfs_filter'],
    },
}
(pre / 'precommit-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
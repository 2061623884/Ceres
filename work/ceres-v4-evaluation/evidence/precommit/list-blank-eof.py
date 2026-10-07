import json,re
from pathlib import Path
root=Path.cwd(); pre=root/'work/ceres-v4-evaluation/evidence/precommit'
audit=json.loads((pre/'precommit-audit.stdout.json').read_text(encoding='utf-8'))
lines=[line for line in audit['git_diff_cached_check']['stdout'].splitlines() if 'new blank line at EOF' in line]
result={'count':len(lines),'lines':lines}
(pre/'blank-eof-details.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
import hashlib
import json
from pathlib import Path
files = sorted([*Path('scripts').glob('eval_v4*.py'), *Path('scripts').glob('test_eval_v4*.py')])
compiled = []
for path in files:
    data = path.read_bytes()
    compile(data, str(path), 'exec')
    compiled.append({'path': path.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
print(json.dumps({'compiled': len(compiled), 'files': compiled}, ensure_ascii=False, indent=2))

import zipfile
from pathlib import Path
z=zipfile.ZipFile('work/ceres-v3/04/review-v1/review-source.zip')
for name in ['backend/app/services/chat_opening_service.py','work/ceres-v3/03/demo.html']:
    raw=z.read(name).decode('utf-8')
    print(f'--- {name} ---')
    if name.endswith('chat_opening_service.py'):
        lines=raw.splitlines()
        for i,line in enumerate(lines,1):
            if 60 <= i <= 82: print(f'{i:4}: {line}')
    else:
        for i,line in enumerate(raw.splitlines(),1): print(f'{i:4}: {line}')

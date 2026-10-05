import json, os, subprocess, sys
from datetime import datetime, timezone

def utc(): return datetime.now(timezone.utc).isoformat()
config_path = sys.argv[1]
configs = json.load(open(config_path, encoding='utf-8-sig'))
remove_exact = {'NODE_ENV','OPENAI_API_KEY','EMBEDDING_API_KEY','INTERNAL_ADMIN_TOKEN','FIGMA_PUBLIC_URL'}
results = []
for item in configs:
    env = os.environ.copy()
    for key in list(env):
        if key in remove_exact or key.startswith('VITE_'):
            env.pop(key, None)
    env['FIGMA_PUBLIC_URL'] = ''
    env['CERES_FRONTEND_DIR'] = os.path.join(item['cwd'])
    start = utc()
    argv = [item['node'], *item['argv']]
    result = subprocess.run(argv, cwd=item['cwd'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    end = utc()
    out = result.stdout
    err = result.stderr
    open(item['stdout'], 'w', encoding='utf-8', newline='').write(out)
    open(item['stderr'], 'w', encoding='utf-8', newline='').write(err)
    record = {'name': item['name'], 'startUtc': start, 'endUtc': end, 'executable': item['node'], 'argv': argv, 'cwd': item['cwd'], 'env': {'removedExact': sorted(remove_exact), 'removedPrefix':'VITE_', 'FIGMA_PUBLIC_URL':'', 'CERES_FRONTEND_DIR':item['cwd']}, 'exit': result.returncode, 'stdoutFile': item['stdout'], 'stderrFile': item['stderr'], 'stdout': out, 'stderr': err}
    if 'dist' in item: record['externalDist'] = item['dist']
    open(item['record'], 'w', encoding='utf-8').write(json.dumps(record, ensure_ascii=False, indent=2))
    results.append(record)
    print(json.dumps({'name':record['name'],'startUtc':start,'endUtc':end,'exit':result.returncode,'stdout':out,'stderr':err,'record':item['record']}, ensure_ascii=False))
summary = {'runs': [{'name':r['name'],'exit':r['exit'],'record':configs[i]['record']} for i,r in enumerate(results)]}
open(os.path.join(os.path.dirname(config_path),'frontend-runner-summary.json'),'w',encoding='utf-8').write(json.dumps(summary,ensure_ascii=False,indent=2))
sys.exit(0 if all(r['exit']==0 for r in results) else 9)

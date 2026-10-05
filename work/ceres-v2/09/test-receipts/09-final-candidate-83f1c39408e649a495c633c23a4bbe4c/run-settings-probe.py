import json, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
root=Path(sys.argv[1]); clone=Path(sys.argv[2]); py=Path(sys.argv[3]); probe=sys.argv[4]; run=Path(sys.argv[5])
env=os.environ.copy(); dotenv=clone/'.env'
keys=[]
for line in dotenv.read_text(encoding='utf-8-sig').splitlines():
    m=re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=',line)
    if m: keys.append(m.group(1))
for key in keys: env.pop(key,None)
env['PYTHONUTF8']='1'; env['PYTHONDONTWRITEBYTECODE']='1'; env['PYTHONPATH']=str(clone/'backend'); env['DATABASE_URL']='sqlite:///'+str(run/'isolated-databases'/'settings-probe.sqlite3').replace('\\','/'); env['MERCURY_DB_PATH']=str(run/'isolated-databases'/'settings-probe-mercury.sqlite3'); env['SOURCE_DATABASE_PATH']=str(run/'isolated-databases'/'no-source.sqlite3')
cmd=[str(py),'-X','utf8','-c',probe]; start=datetime.now(timezone.utc).isoformat(); result=subprocess.run(cmd,cwd=clone/'backend',env=env,capture_output=True,text=True,encoding='utf-8',errors='replace'); end=datetime.now(timezone.utc).isoformat()
(run/'settings-probe.stdout.txt').write_text(result.stdout,encoding='utf-8'); (run/'settings-probe.stderr.txt').write_text(result.stderr,encoding='utf-8'); (run/'settings-probe.exit-code.txt').write_text(str(result.returncode),encoding='ascii')
record={'startUtc':start,'endUtc':end,'executable':str(py),'argv':cmd[1:],'cwd':str(clone/'backend'),'environment':'Ceres root .env keys removed from process so Settings loads cold-1 root .env; only isolated DB/source paths, PYTHONUTF8/PYTHONDONTWRITEBYTECODE, PYTHONPATH=cold-1/backend provided','dotenvKeyNamesRemoved':sorted(keys),'exit':result.returncode,'stdoutFile':str(run/'settings-probe.stdout.txt'),'stderrFile':str(run/'settings-probe.stderr.txt'),'stdout':result.stdout,'stderr':result.stderr}
(run/'settings-probe.command.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'record':str(run/'settings-probe.command.json')},ensure_ascii=False)); sys.exit(result.returncode)

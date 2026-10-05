from __future__ import annotations
import hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

attempt=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-586811ddb2444ed68f19397d6372d83f')
temp=attempt/'browser-temp'
node=Path(r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
scenario=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v2\09\ui-order-controls.cjs')
playwright=Path(r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright')
chrome=Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
urls=['http://127.0.0.71:5171/','http://127.0.0.72:5172/']
argv=[str(node),str(scenario),str(attempt),str(playwright),str(chrome),*urls]
env=os.environ.copy()
env.update({'TEMP':str(temp),'TMP':str(temp),'LLM_MODE':'offline','LLM_MODEL':'','MEMORY_MODEL':'','OPENAI_BASE_URL':'','OPENAI_API_KEY':'','PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
started=datetime.now(timezone.utc).isoformat()
scene_sha=hashlib.sha256(scenario.read_bytes()).hexdigest().upper()
proc=subprocess.run(argv,cwd=str(attempt),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(attempt/'ui-order-controls.stdout.raw.txt').write_text(proc.stdout,encoding='utf-8')
(attempt/'ui-order-controls.stderr.raw.txt').write_text(proc.stderr,encoding='utf-8')
receipt={'started_utc':started,'finished_utc':finished,'scenario_sha256':scene_sha,'argv':argv,'runner_argv':sys.orig_argv,'cwd':str(attempt),'python_executable':sys.executable,'node_path':str(node),'scenario_path':str(scenario),'playwright_module':str(playwright),'chrome_executable':str(chrome),'urls':urls,'environment':{k:env[k] for k in ('TEMP','TMP','LLM_MODE','LLM_MODEL','MEMORY_MODEL','OPENAI_BASE_URL','OPENAI_API_KEY','PYTHONUTF8','PYTHONDONTWRITEBYTECODE')},'exit_code':proc.returncode,'stdout_file':str(attempt/'ui-order-controls.stdout.raw.txt'),'stderr_file':str(attempt/'ui-order-controls.stderr.raw.txt')}
(attempt/'ui-order-controls.command.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'started_utc':started,'finished_utc':finished,'scenario_sha256':scene_sha,'argv':argv,'cwd':str(attempt),'environment':receipt['environment'],'exit_code':proc.returncode,'stdout_file':receipt['stdout_file'],'stderr_file':receipt['stderr_file']},ensure_ascii=False,indent=2))
print('--- NODE STDOUT ---')
print(proc.stdout,end='')
print('--- NODE STDERR ---')
print(proc.stderr,end='')
raise SystemExit(proc.returncode)

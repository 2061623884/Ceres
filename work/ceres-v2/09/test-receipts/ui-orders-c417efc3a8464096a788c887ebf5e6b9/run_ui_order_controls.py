from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

runner = Path(__file__).resolve()
root = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9')
node = Path(r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
scenario = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v2\09\ui-order-controls.cjs')
playwright = Path(r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright')
chrome = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
urls = ['http://127.0.0.71:5171/','http://127.0.0.72:5172/']
argv=[str(node),str(scenario),str(root),str(playwright),str(chrome),*urls]
env=os.environ.copy()
env.update({'LLM_MODE':'offline','LLM_MODEL':'','MEMORY_MODEL':'','OPENAI_BASE_URL':'','OPENAI_API_KEY':'','PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
started=datetime.now(timezone.utc).isoformat()
proc=subprocess.run(argv,cwd=str(root),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(root/'ui-order-controls.stdout.raw.txt').write_text(proc.stdout,encoding='utf-8')
(root/'ui-order-controls.stderr.raw.txt').write_text(proc.stderr,encoding='utf-8')
receipt={'started_utc':started,'finished_utc':finished,'argv':argv,'runner_argv':sys.orig_argv,'cwd':str(root),'python_executable':sys.executable,'node_path':str(node),'scenario_path':str(scenario),'playwright_module':str(playwright),'chrome_executable':str(chrome),'urls':urls,'environment':{k:env[k] for k in ('LLM_MODE','LLM_MODEL','MEMORY_MODEL','OPENAI_BASE_URL','OPENAI_API_KEY','PYTHONUTF8','PYTHONDONTWRITEBYTECODE')},'exit_code':proc.returncode,'stdout_file':str(root/'ui-order-controls.stdout.raw.txt'),'stderr_file':str(root/'ui-order-controls.stderr.raw.txt')}
(root/'ui-order-controls.command.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'started_utc':started,'finished_utc':finished,'argv':argv,'cwd':str(root),'environment':receipt['environment'],'exit_code':proc.returncode,'stdout_file':receipt['stdout_file'],'stderr_file':receipt['stderr_file']},ensure_ascii=False,indent=2))
print('--- NODE STDOUT ---')
print(proc.stdout,end='')
print('--- NODE STDERR ---')
print(proc.stderr,end='')
raise SystemExit(proc.returncode)

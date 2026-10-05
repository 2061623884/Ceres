from __future__ import annotations
import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
attempt=Path(sys.argv[1]); ps=attempt/'verify_ui_services_stopped.ps1'
argv=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps),str(attempt)]
started=datetime.now(timezone.utc).isoformat()
proc=subprocess.run(argv,cwd=str(attempt),capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(attempt/'service-cleanup-verification.stdout.raw.txt').write_text(proc.stdout,encoding='utf-8')
(attempt/'service-cleanup-verification.stderr.raw.txt').write_text(proc.stderr,encoding='utf-8')
receipt={'started_utc':started,'finished_utc':finished,'argv':argv,'cwd':str(attempt),'runner_executable':sys.executable,'exit_code':proc.returncode,'stdout_file':str(attempt/'service-cleanup-verification.stdout.raw.txt'),'stderr_file':str(attempt/'service-cleanup-verification.stderr.raw.txt')}
(attempt/'service-cleanup-verification.command.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(receipt,indent=2)); print('--- STDOUT ---'); print(proc.stdout,end=''); print('--- STDERR ---'); print(proc.stderr,end='')
raise SystemExit(proc.returncode)

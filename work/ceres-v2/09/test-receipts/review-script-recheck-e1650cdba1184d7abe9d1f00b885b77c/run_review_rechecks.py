from __future__ import annotations
import hashlib, json, os, subprocess, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

repo=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres')
run=Path(sys.argv[1]); run.mkdir(parents=True,exist_ok=True)
verify_output=run/('service-verification-'+uuid.uuid4().hex); verify_output.mkdir(parents=True,exist_ok=True)
py=repo/'backend'/'.venv'/'Scripts'/'python.exe'
script_paths={
 'corrected_journey_runner':repo/'work'/'ceres-v2'/'09'/'test-receipts'/'09-corrected-journey-fb5a1006ddc74188903a615f40009b75'/'corrected-journey-runner.py',
 'readonly_live_trace':repo/'work'/'ceres-v2'/'09'/'test-receipts'/'09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'/'readonly-live-trace.py',
 'trace_readonly':repo/'work'/'ceres-v2'/'09'/'test-receipts'/'09-corrected-journey-fb5a1006ddc74188903a615f40009b75'/'trace_readonly.py',
 'stop_ui_services':repo/'work'/'ceres-v2'/'09'/'test-receipts'/'ui-orders-c417efc3a8464096a788c887ebf5e6b9'/'effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826'/'stop_ui_services_exact_pids.ps1',
 'verify_ui_services':repo/'work'/'ceres-v2'/'09'/'test-receipts'/'ui-orders-c417efc3a8464096a788c887ebf5e6b9'/'effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826'/'verify_ui_services_stopped.ps1'
}
for path in script_paths.values():
    if not path.is_file(): raise FileNotFoundError(str(path))
hashes_before={name:hashlib.sha256(path.read_bytes()).hexdigest().upper() for name,path in script_paths.items()}
verify_source=script_paths['verify_ui_services'].read_text(encoding='utf-8-sig')
if 'Stop-Process' in verify_source: raise RuntimeError('Refusing to execute a verification script containing Stop-Process.')

code='\n'.join(['import ast, pathlib, sys','for item in sys.argv[1:]:',' p=pathlib.Path(item); ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p)); print("AST_OK "+p.name)'])
python_argv=[str(py),'-X','utf8','-c',code,*[str(script_paths[name]) for name in ('corrected_journey_runner','readonly_live_trace','trace_readonly')]]
env=os.environ.copy(); env.update({'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
started=datetime.now(timezone.utc).isoformat()
python_proc=subprocess.run(python_argv,cwd=str(repo),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(run/'python-ast.stdout.raw.txt').write_text(python_proc.stdout,encoding='utf-8'); (run/'python-ast.stderr.raw.txt').write_text(python_proc.stderr,encoding='utf-8')
python_receipt={'started_utc':started,'finished_utc':finished,'argv':python_argv,'cwd':str(repo),'executable':str(py),'environment':{'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'},'script_sha256':{name:hashes_before[name] for name in ('corrected_journey_runner','readonly_live_trace','trace_readonly')},'exit_code':python_proc.returncode,'stdout_file':str(run/'python-ast.stdout.raw.txt'),'stderr_file':str(run/'python-ast.stderr.raw.txt')}
(run/'python-ast.command.json').write_text(json.dumps(python_receipt,ensure_ascii=False,indent=2),encoding='utf-8')
if python_proc.returncode != 0:
 print(json.dumps(python_receipt,ensure_ascii=False,indent=2)); print(python_proc.stdout,end=''); print(python_proc.stderr,end='',file=sys.stderr); raise SystemExit(python_proc.returncode)

ps_parser=run/'parse_ui_scripts.ps1'
ps_parser.write_text(r'''$ErrorActionPreference = 'Stop'
$targets = @(
  @{ Label = 'stop_ui'; Relative = 'work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\stop_ui_services_exact_pids.ps1' },
  @{ Label = 'verify_ui'; Relative = 'work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\verify_ui_services_stopped.ps1' }
)
$failed = $false
foreach ($target in $targets) {
  $full = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $target.Relative))
  if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { [Console]::Error.WriteLine("MISSING_TARGET $($target.Label)"); $failed = $true; continue }
  $tokens = $null
  $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errors) | Out-Null
  if ($errors.Count -gt 0) {
    $failed = $true
    foreach ($errorItem in $errors) { [Console]::Error.WriteLine("PARSE_ERROR $($target.Label) $($errorItem.Extent.StartLineNumber):$($errorItem.Extent.StartColumnNumber) $($errorItem.Message)") }
  } else { Write-Output "PARSE_OK $($target.Label)" }
}
if ($failed) { exit 1 }
''',encoding='utf-8')
ps_argv=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps_parser)]
started=datetime.now(timezone.utc).isoformat()
ps_proc=subprocess.run(ps_argv,cwd=str(repo),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(run/'powershell-parser.stdout.raw.txt').write_text(ps_proc.stdout,encoding='utf-8'); (run/'powershell-parser.stderr.raw.txt').write_text(ps_proc.stderr,encoding='utf-8')
ps_receipt={'started_utc':started,'finished_utc':finished,'argv':ps_argv,'cwd':str(repo),'script_sha256':{name:hashes_before[name] for name in ('stop_ui_services','verify_ui_services')},'exit_code':ps_proc.returncode,'stdout_file':str(run/'powershell-parser.stdout.raw.txt'),'stderr_file':str(run/'powershell-parser.stderr.raw.txt')}
(run/'powershell-parser.command.json').write_text(json.dumps(ps_receipt,ensure_ascii=False,indent=2),encoding='utf-8')
if ps_proc.returncode != 0:
 print(json.dumps(ps_receipt,ensure_ascii=False,indent=2)); print(ps_proc.stdout,end=''); print(ps_proc.stderr,end='',file=sys.stderr); raise SystemExit(ps_proc.returncode)

verify_argv=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script_paths['verify_ui_services']),str(verify_output)]
started=datetime.now(timezone.utc).isoformat()
verify_proc=subprocess.run(verify_argv,cwd=str(repo),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
finished=datetime.now(timezone.utc).isoformat()
(run/'readonly-verification.stdout.raw.txt').write_text(verify_proc.stdout,encoding='utf-8'); (run/'readonly-verification.stderr.raw.txt').write_text(verify_proc.stderr,encoding='utf-8')
hashes_after={name:hashlib.sha256(path.read_bytes()).hexdigest().upper() for name,path in script_paths.items()}
verify_receipt={'started_utc':started,'finished_utc':finished,'argv':verify_argv,'cwd':str(repo),'environment':{'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'},'script_sha256_before':hashes_before['verify_ui_services'],'script_sha256_after':hashes_after['verify_ui_services'],'output_directory':str(verify_output),'exit_code':verify_proc.returncode,'stdout_file':str(run/'readonly-verification.stdout.raw.txt'),'stderr_file':str(run/'readonly-verification.stderr.raw.txt')}
(run/'readonly-verification.command.json').write_text(json.dumps(verify_receipt,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'run_directory':str(run),'verify_output_directory':str(verify_output),'python_ast':python_receipt,'powershell_parse':ps_receipt,'readonly_verification':verify_receipt,'all_script_hashes_before':hashes_before,'all_script_hashes_after':hashes_after}
(run/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2)); print('--- PYTHON AST STDOUT ---'); print(python_proc.stdout,end=''); print('--- POWERSHELL PARSER STDOUT ---'); print(ps_proc.stdout,end=''); print('--- READONLY VERIFICATION STDOUT ---'); print(verify_proc.stdout,end=''); print('--- READONLY VERIFICATION STDERR ---'); print(verify_proc.stderr,end='')
raise SystemExit(verify_proc.returncode)

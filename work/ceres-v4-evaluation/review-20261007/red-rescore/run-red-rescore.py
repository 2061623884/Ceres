import json,os,subprocess
from pathlib import Path
root=Path.cwd(); out=root/'work/ceres-v4-evaluation/review-20261007/red-rescore'
python=r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
tests=['test_eval_v4.ScoringTests.test_rescore_preserves_preparation_and_runner_failures','test_eval_v4.ScoringTests.test_rescore_keeps_missing_attempts_and_unexecuted_tasks_in_denominator']
args=[python,'-X','utf8','-m','unittest',*tests,'-v']
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'; cwd=root/'scripts'
(out/'red-rescore.command.txt').write_text(subprocess.list2cmdline(args)+'\n',encoding='utf-8')
(out/'environment.json').write_text(json.dumps({'python_executable':python,'python_version':subprocess.run([python,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),'cwd':str(cwd),'test_bytecode_writes_disabled':True,'target_tests':tests},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
p=subprocess.run(args,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(out/'red-rescore.stdout.txt').write_bytes(p.stdout); (out/'red-rescore.stderr.txt').write_bytes(p.stderr)
(out/'red-rescore.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
print(json.dumps({'command':args,'cwd':str(cwd),'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace')},ensure_ascii=False,indent=2))
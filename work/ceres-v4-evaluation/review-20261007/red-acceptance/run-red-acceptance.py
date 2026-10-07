import json,os,subprocess
from pathlib import Path
root=Path.cwd(); out=root/'work/ceres-v4-evaluation/review-20261007/red-acceptance'
python=r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
test='test_eval_v4_record.AcceptanceTests.test_stale_api_or_ui_summary_cannot_be_archived'
args=[python,'-X','utf8','-m','unittest',test,'-v']
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'; cwd=root/'scripts'
(out/'red-acceptance.command.txt').write_text(subprocess.list2cmdline(args)+'\n',encoding='utf-8')
(out/'environment.json').write_text(json.dumps({'python_executable':python,'python_version':subprocess.run([python,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),'cwd':str(cwd),'test_bytecode_writes_disabled':True,'target_test':test},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
p=subprocess.run(args,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(out/'red-acceptance.stdout.txt').write_bytes(p.stdout); (out/'red-acceptance.stderr.txt').write_bytes(p.stderr)
(out/'red-acceptance.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
print(json.dumps({'command':args,'cwd':str(cwd),'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace')},ensure_ascii=False,indent=2))
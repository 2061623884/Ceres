import hashlib,os,subprocess,json
from pathlib import Path
root=Path.cwd(); out=root/'work/ceres-v4-evaluation/review-20261007/green-checkpoint'
python=r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
args=[python,'-X','utf8','-m','unittest','discover','-s','scripts','-p','test_eval_v4.py','-v']
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'
(out/'green-checkpoint.command.txt').write_text(subprocess.list2cmdline(args)+'\n',encoding='utf-8')
(out/'environment.json').write_text(json.dumps({'python_executable':python,'python_version':subprocess.run([python,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),'cwd':str(root),'test_bytecode_writes_disabled':True},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
p=subprocess.run(args,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(out/'green-checkpoint.stdout.txt').write_bytes(p.stdout); (out/'green-checkpoint.stderr.txt').write_bytes(p.stderr)
(out/'green-checkpoint.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
print(json.dumps({'command':args,'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace')},ensure_ascii=False,indent=2))
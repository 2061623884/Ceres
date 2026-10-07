import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path.cwd(); out=root/'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked-validation'
python=r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
node=r'C:\Users\20616\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def git(args):
 p=subprocess.run(['git',*args],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 return {'command':['git',*args],'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace')}
def command_record(name,args,env):
 p=subprocess.run(args,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 (out/f'{name}.stdout.txt').write_bytes(p.stdout); (out/f'{name}.stderr.txt').write_bytes(p.stderr)
 (out/f'{name}.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
 (out/f'{name}.command.txt').write_text(subprocess.list2cmdline(args)+'\n',encoding='utf-8')
 return {'command':args,'exit_code':p.returncode,'stdout_bytes':len(p.stdout),'stderr_bytes':len(p.stderr),'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()}
code_files=sorted([*root.glob('scripts/eval_v4*.py'),*root.glob('scripts/test_eval_v4*.py')])
code_hashes_before={str(p.relative_to(root)):sha(p) for p in code_files}
index_before=git(['diff','--cached','--name-only','-z'])
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'
test_args=[python,'-X','utf8','-m','unittest','discover','-s','scripts','-p','test_eval_v4*.py','-v']
compile_code="from pathlib import Path; files="+repr([str(p.relative_to(root)) for p in code_files])+"; [compile(Path(name).read_bytes(), name, 'exec') for name in files]; print('compiled: ' + ', '.join(files))"
compile_args=[python,'-X','utf8','-c',compile_code]
tests=command_record('reporter-tests',test_args,env)
compile_result=command_record('python-compile',compile_args,env)
code_hashes_after={str(p.relative_to(root)):sha(p) for p in code_files}
receipt={'python_executable':python,'python_version':subprocess.run([python,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),'node_executable':node,
 'node_version':subprocess.run([node,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),
 'code_hashes_before':code_hashes_before,'code_hashes_after':code_hashes_after,'code_hashes_unchanged':code_hashes_before==code_hashes_after,
 'index_paths_before':index_before,'index_paths_after':git(['diff','--cached','--name-only','-z']),
 'tests':tests,'compile':compile_result,'all_checks_passed':tests['exit_code']==0 and compile_result['exit_code']==0 and code_hashes_before==code_hashes_after}
(out/'validation-preflight.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'tests_exit':tests['exit_code'],'compile_exit':compile_result['exit_code'],'code_hashes_unchanged':receipt['code_hashes_unchanged'],'all_checks_passed':receipt['all_checks_passed'],'test_stderr_sha256':tests['stderr_sha256'],'compile_stdout_sha256':compile_result['stdout_sha256']},ensure_ascii=False,indent=2))
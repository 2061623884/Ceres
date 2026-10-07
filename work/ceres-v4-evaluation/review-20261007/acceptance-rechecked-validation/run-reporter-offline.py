import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path.cwd(); evidence=root/'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked-validation'
python=r'C:\Users\20616\AppData\Local\Programs\Python\Python312\python.exe'
inputs={
 'run04':'work/ceres-v4-evaluation/run-04',
 'ui02':'work/ceres-v4-evaluation/ui/run-02',
 'diagnostics_v3':'work/ceres-v4-evaluation/diagnostics-run03-v3',
 'probe_v1':'work/ceres-v4-evaluation/diagnostics-run03',
 'probe_v2':'work/ceres-v4-evaluation/diagnostics-run03-v2',
 'old_acceptance':'work/ceres-v4-evaluation/acceptance',
}
output='work/ceres-v4-evaluation/review-20261007/acceptance-rechecked'
if (root/output).exists():
    raise SystemExit(f'refusing to overwrite existing output directory: {output}')
def sha(b): return hashlib.sha256(b).hexdigest()
def file_sha(path): return sha(path.read_bytes())
def tree_manifest(rel):
    directory=root/rel
    files=[]
    for path in sorted(p for p in directory.rglob('*') if p.is_file()):
        files.append({'path':str(path.relative_to(root)).replace('\\','/'),'size':path.stat().st_size,'sha256':file_sha(path)})
    payload=''.join(f"{row['path']}\0{row['size']}\0{row['sha256']}\n" for row in files).encode('utf-8')
    return {'root':rel,'file_count':len(files),'tree_sha256':sha(payload),'files':files}
code_files=sorted([*root.glob('scripts/eval_v4*.py'),*root.glob('scripts/test_eval_v4*.py')])
code_before={str(p.relative_to(root)).replace('\\','/'):file_sha(p) for p in code_files}
inputs_before={name:tree_manifest(path) for name,path in inputs.items()}
index_before=subprocess.run(['git','diff','--cached','--name-only','-z'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
args=[python,'-X','utf8','scripts/eval_v4_record.py','--source',inputs['run04'],'--ui',inputs['ui02']+'/result.json','--diagnostics',inputs['diagnostics_v3'],'--probe',inputs['probe_v1'],'--probe',inputs['probe_v2'],'--output',output]
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'
(evidence/'reporter-recheck.command.txt').write_text(subprocess.list2cmdline(args)+'\n',encoding='utf-8')
p=subprocess.run(args,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(evidence/'reporter-recheck.stdout.txt').write_bytes(p.stdout); (evidence/'reporter-recheck.stderr.txt').write_bytes(p.stderr)
(evidence/'reporter-recheck.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
inputs_after={name:tree_manifest(path) for name,path in inputs.items()}
code_after={str(p.relative_to(root)).replace('\\','/'):file_sha(p) for p in code_files}
index_after=subprocess.run(['git','diff','--cached','--name-only','-z'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
index_unchanged=index_before.stdout==index_after.stdout and index_before.returncode==index_after.returncode
manifest={'python_executable':python,'python_version':subprocess.run([python,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8',errors='replace').strip(),
 'command':args,'exit_code':p.returncode,'stdout_bytes':len(p.stdout),'stderr_bytes':len(p.stderr),'stdout_sha256':sha(p.stdout),'stderr_sha256':sha(p.stderr),
 'input_hashes_before':inputs_before,'input_hashes_after':inputs_after,'input_hashes_unchanged':inputs_before==inputs_after,
 'source_code_hashes_before':code_before,'source_code_hashes_after':code_after,'source_code_hashes_unchanged':code_before==code_after,
 'index_paths_unchanged':index_unchanged,'output_directory_created':(root/output).is_dir(),
 'output_files':sorted(str(p.relative_to(root)).replace('\\','/') for p in (root/output).rglob('*') if p.is_file()) if (root/output).exists() else [],
 'no_product_model_or_ui_execution':True}
(evidence/'reporter-recheck-execution.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace'),
 'input_hashes_unchanged':manifest['input_hashes_unchanged'],'source_code_hashes_unchanged':manifest['source_code_hashes_unchanged'],'index_paths_unchanged':index_unchanged,
 'output_directory_created':manifest['output_directory_created'],'output_file_count':len(manifest['output_files'])},ensure_ascii=False,indent=2))
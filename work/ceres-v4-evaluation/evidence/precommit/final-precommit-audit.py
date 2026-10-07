import hashlib, json, re, subprocess
from collections import Counter
from pathlib import Path
root=Path.cwd(); pre=root/'work/ceres-v4-evaluation/evidence/precommit'
def run(args, cwd=root):
    p=subprocess.run(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return {'command':args,'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace'),'stdout_bytes':len(p.stdout),'stderr_bytes':len(p.stderr),'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()}
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_path(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def index_bytes(path):
    p=subprocess.run(['git','show',f':{path}'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise RuntimeError(f'git show index failed for {path}: {p.stderr.decode(errors="replace")}')
    return p.stdout
repo=run(['git','rev-parse','--show-toplevel'])
stage_raw=subprocess.run(['git','diff','--cached','--name-only','-z'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
if stage_raw.returncode: raise RuntimeError(stage_raw.stderr.decode(errors='replace'))
staged_paths=[p.decode('utf-8') for p in stage_raw.stdout.split(b'\0') if p]
(pre/'final-staged-paths.txt').write_text(''.join(p+'\n' for p in staged_paths),encoding='utf-8')
stage_check=run(['git','diff','--cached','--check'])
forbidden_pattern=re.compile(r'(^|/)(\.env(?:\..*)?|__pycache__|cache)(/|$)|\.(?:sqlite3?|db|pyc)$|(?:-wal|-shm)$',re.I)
forbidden=sorted(p for p in staged_paths if forbidden_pattern.search(p))
tasks={
 'tasks/ceres-v4-evaluation.md','tasks/ceres-v4-evaluation-01-core-pilot.md','tasks/ceres-v4-evaluation-02-full-task-evaluation.md',
 'tasks/ceres-v4-evaluation-03-browser-journeys.md','tasks/ceres-v4-evaluation-04-acceptance-record.md','tasks/ceres-v4-repair-aftersales.md',
 'tasks/ceres-v4-repair-latency.md','tasks/ceres-v4-repair-memory.md','tasks/ceres-v4-repair-shopping.md'}
exact={'README.md','docs/plans/ceres-v4-evaluation-spec.md','logs/ceres-v4-evaluation.md','scripts/.gitattributes',
 'scripts/eval_v4.py','scripts/eval_v4_judge.py','scripts/eval_v4_record.py','scripts/eval_v4_ui.mjs','scripts/test_eval_v4.py'}|tasks
def allowed(p): return p in exact or p.startswith('evals/v4/') or p.startswith('work/ceres-v4-evaluation/')
unexpected=sorted(p for p in staged_paths if not allowed(p))
missing=sorted(p for p in exact if p not in staged_paths)
def numstat(args):
    r=run(args)
    if r['exit_code'] or not r['stdout'].strip(): return r|{'parsed':None if r['exit_code'] else {'added':0,'deleted':0,'path':None}}
    a,d,p=r['stdout'].strip().split('\t',2)
    return r|{'parsed':{'added':int(a),'deleted':int(d),'path':p}}
cached_num=numstat(['git','diff','--cached','--numstat','--','README.md'])
unstaged_num=numstat(['git','diff','--numstat','--','README.md'])
cached_patch=run(['git','diff','--cached','--unified=0','--','README.md'])
unstaged_patch=run(['git','diff','--unified=0','--','README.md'])
def added_lines(patch): return [line[1:] for line in patch['stdout'].splitlines() if line.startswith('+') and not line.startswith('+++')]
cached_adds=added_lines(cached_patch); unstaged_adds=added_lines(unstaged_patch)
readme_ok=(cached_num['parsed']=={'added':1,'deleted':0,'path':'README.md'} and unstaged_num['parsed']=={'added':7,'deleted':0,'path':'README.md'} and len(cached_adds)==1 and len(unstaged_adds)==7)
candidate=root/'work/.ceres-next-08'; expected_head='ac895fd620af617fa31f4e0006841a4d6a89cd53'
candidate_head=run(['git','-C',str(candidate),'rev-parse','HEAD'])
candidate_status=run(['git','-C',str(candidate),'status','--short','--untracked-files=no'])
candidate_diff=run(['git','-C',str(candidate),'diff','HEAD','--quiet'])
candidate_ok=candidate_head['stdout'].strip()==expected_head and candidate_status['stdout'].strip()=='' and candidate_diff['exit_code']==0
snapshots={
 'scripts/eval_v4.py':'work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4.py.frozen.py',
 'scripts/test_eval_v4.py':'work/ceres-v4-evaluation/evidence/rescore-run04/test_eval_v4.py.frozen.py',
 'scripts/eval_v4_judge.py':'work/ceres-v4-evaluation/evidence/diag-run03-v3/eval_v4_judge.frozen.py',
 'scripts/eval_v4_record.py':'work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4_record.py.final-frozen.py',
 'scripts/eval_v4_ui.mjs':'work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4_ui.current.frozen.mjs',
 'evals/v4/cases.json':'work/ceres-v4-evaluation/evidence/rescore-run04/cases.v2.frozen.json'}
hashes=[]
for source,snapshot in snapshots.items():
    current=sha_path(root/source); frozen=sha_path(root/snapshot); staged=sha_bytes(index_bytes(source))
    hashes.append({'path':source,'current_sha256':current,'frozen_sha256':frozen,'staged_sha256':staged,
                   'current_matches_frozen':current==frozen,'staged_matches_frozen':staged==frozen})
acceptance=json.loads((root/'work/ceres-v4-evaluation/acceptance/acceptance.json').read_text(encoding='utf-8'))
manifest=json.loads((root/'work/ceres-v4-evaluation/run-04/manifest.json').read_text(encoding='utf-8'))
record_sha=next(x['staged_sha256'] for x in hashes if x['path']=='scripts/eval_v4_record.py')
runner_sha=next(x['staged_sha256'] for x in hashes if x['path']=='scripts/eval_v4.py')
cases_sha=next(x['staged_sha256'] for x in hashes if x['path']=='evals/v4/cases.json')
report_hashes={'acceptance_reporter_sha256':acceptance['reporter_sha256'],'current_record_sha256':sha_path(root/'scripts/eval_v4_record.py'),'staged_record_sha256':record_sha,
 'run04_runner_sha256':manifest['runner_sha256'],'staged_runner_sha256':runner_sha,'run04_cases_sha256':manifest['cases_sha256'],'staged_cases_sha256':cases_sha}
hash_ok=all(x['current_matches_frozen'] and x['staged_matches_frozen'] for x in hashes)
report_ok=report_hashes['acceptance_reporter_sha256']==report_hashes['current_record_sha256']==record_sha
manifest_ok=report_hashes['run04_runner_sha256']==runner_sha and report_hashes['run04_cases_sha256']==cases_sha
assets=[]
for path in staged_paths:
    if Path(path).suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.zip'}: continue
    raw=index_bytes(path); attr=run(['git','check-attr','--cached','filter','--',path])
    text=raw.decode('ascii',errors='replace')
    oid=re.search(r'(?m)^oid sha256:([0-9a-f]{64})$',text); size=re.search(r'(?m)^size ([0-9]+)$',text)
    pointer=raw.startswith(b'version https://git-lfs.github.com/spec/v1\n') and oid is not None and size is not None
    assets.append({'path':path,'staged_blob_bytes':len(raw),'lfs_pointer':pointer,'lfs_filter':'filter: lfs' in attr['stdout'],
                   'oid':oid.group(1) if oid else None,'payload_size':int(size.group(1)) if size else None})
lfs_ok=all(x['lfs_pointer'] and x['lfs_filter'] for x in assets)
attrs_path='work/ceres-v4-evaluation/.gitattributes'
attrs_bytes=index_bytes(attrs_path)
attrs_text=attrs_bytes.decode('utf-8',errors='replace')
attribute_probes={}
for p in ['work/ceres-v4-evaluation/run-03/R01-r1/result.json','work/ceres-v4-evaluation/evidence/rescore-run04/acceptance_audit.py',
          'work/ceres-v4-evaluation/evidence/rescore-run04/acceptance_audit.v2.py','work/ceres-v4-evaluation/ui/run-02-service-verify-attempt01.stderr.txt']:
    attribute_probes[p]=run(['git','check-attr','--cached','text','whitespace','--',p])
first_receipt=root/'work/ceres-v4-evaluation/evidence/precommit/precommit-audit.stdout.json'
first_receipt_sha=sha_path(first_receipt)
first_receipt_bytes=first_receipt.stat().st_size
precommit_status=run(['git','status','--short','--','work/ceres-v4-evaluation/evidence/precommit'])
result={
 'repo_root':repo['stdout'].strip(),'staged_count':len(staged_paths),'task_count':len([p for p in staged_paths if p in tasks]),
 'allowed_scope':{'unexpected':unexpected,'missing_required_exact':missing,'forbidden_secret_db_cache':forbidden},
 'git_diff_cached_check':stage_check,
 'README':{'cached_numstat':cached_num,'unstaged_numstat':unstaged_num,'cached_added_lines':cached_adds,'unstaged_added_lines':unstaged_adds,'partial_stage_ok':readme_ok},
 'candidate':{'head':candidate_head['stdout'].strip(),'expected_head':expected_head,'status_tracked':candidate_status,'diff_HEAD_quiet':candidate_diff,'clean':candidate_ok},
 'source_hashes':hashes,'acceptance_manifest_hashes':report_hashes,
 'hash_gates':{'source_cases_match_frozen':hash_ok,'acceptance_reporter_matches_current_staged':report_ok,'run04_runner_cases_match_staged':manifest_ok},
 'lfs_assets':assets,'lfs_assets_all_pointer_with_lfs_filter':lfs_ok,
 'work_attributes':{'staged_path':attrs_path,'sha256':sha_bytes(attrs_bytes),'content':attrs_text,'effective_probes':attribute_probes},
 'prior_full_audit_receipt':{'path':'work/ceres-v4-evaluation/evidence/precommit/precommit-audit.stdout.json','bytes':first_receipt_bytes,'sha256':first_receipt_sha,'status':precommit_status},
 'final_pass':not unexpected and not missing and not forbidden and stage_check['exit_code']==0 and readme_ok and candidate_ok and hash_ok and report_ok and manifest_ok and lfs_ok}
(pre/'final-precommit-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
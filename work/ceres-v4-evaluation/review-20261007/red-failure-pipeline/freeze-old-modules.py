import hashlib,json,subprocess
from pathlib import Path
root=Path.cwd(); out=root/'work/ceres-v4-evaluation/review-20261007/red-failure-pipeline/frozen-old'
old='abd61394437f21c1b474d39c56559a245dc21e97'
modules=['scripts/eval_v4_judge.py','scripts/eval_v4_record.py']
resolved=subprocess.run(['git','rev-parse','abd6139'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
if resolved.returncode or resolved.stdout.decode().strip()!=old: raise SystemExit('unexpected old HEAD resolution')
rows=[]
for path in modules:
    args=['git','show',f'{old}:{path}']; p=subprocess.run(args,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    name=Path(path).name; frozen=out/name
    if p.returncode: raise SystemExit(f'git show failed for {path}: {p.stderr.decode(errors="replace")}')
    frozen.write_bytes(p.stdout)
    (out/f'{name}.git-show.command.txt').write_text('git show '+old+':'+path+'\n',encoding='utf-8')
    (out/f'{name}.git-show.stderr.txt').write_bytes(p.stderr)
    (out/f'{name}.git-show.exit-code.txt').write_text(str(p.returncode)+'\n',encoding='utf-8')
    rows.append({'path':path,'commit':old,'command':args,'exit_code':p.returncode,'bytes':len(p.stdout),'sha256':hashlib.sha256(p.stdout).hexdigest(),'frozen_copy':str(frozen.relative_to(root)).replace('\\','/')})
manifest={'old_commit':old,'resolved_commit':resolved.stdout.decode().strip(),'modules':rows}
(out/'freeze-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
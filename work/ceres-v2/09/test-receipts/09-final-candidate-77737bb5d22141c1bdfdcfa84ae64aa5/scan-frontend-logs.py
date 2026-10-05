import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
envfile=Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres\.env")
secrets=[]
if envfile.exists():
  for line in envfile.read_text(encoding="utf-8",errors="replace").splitlines():
    m=re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$",line)
    if m and re.search(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)",m.group(1),re.I):
      val=m.group(2).strip().strip("\"'").split("#",1)[0].strip()
      if val: secrets.append(val)
run=Path(sys.argv[1])
names=["cold-1-frontend-tsc-stdout.txt","cold-1-frontend-tsc-stderr.txt","cold-1-frontend-build-stdout.txt","cold-1-frontend-build-stderr.txt","cold-1-frontend-tsc-runner-stdout.txt","cold-1-frontend-tsc-runner-stderr.txt","cold-1-frontend-build-runner-stdout.txt","cold-1-frontend-build-runner-stderr.txt"]
result=[]
for name in names:
  p=run/name
  if not p.exists(): continue
  content=p.read_text(encoding="utf-8",errors="replace")
  cred=any(v in content for v in secrets)
  bearer=bool(re.search(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}",content))
  safe=content
  for v in secrets: safe=safe.replace(v,"<REDACTED>")
  safe=re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}",r"\1<REDACTED>",safe)
  dest=run/name.replace(".txt","-sanitized.txt")
  dest.write_text(safe,encoding="utf-8")
  result.append({"file":name,"contains_env_credential":cred,"contains_bearer":bearer,"sanitized_copy":str(dest)})
print(json.dumps({"utc":datetime.now(timezone.utc).isoformat(),"credential_values_loaded_without_output":len(secrets),"results":result},ensure_ascii=False,indent=2))

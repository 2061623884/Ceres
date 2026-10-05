import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
envfile = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres\.env")
secrets = []
if envfile.exists():
  for line in envfile.read_text(encoding="utf-8", errors="replace").splitlines():
    m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
    if m and re.search(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)", m.group(1), re.I):
      v = m.group(2).strip().strip("\"'").split("#", 1)[0].strip()
      if v: secrets.append(v)
run = Path(sys.argv[1])
results=[]
for name in ("cold-1-offline-mercury-stdout.txt","cold-1-offline-mercury-stderr.txt"):
  source=run/name
  content=source.read_text(encoding="utf-8",errors="replace")
  matched=any(s in content for s in secrets)
  bearer=bool(re.search(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}",content))
  safe=content
  for s in secrets: safe=safe.replace(s,"<REDACTED>")
  safe=re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}",r"\1<REDACTED>",safe)
  dest=run/name.replace(".txt","-sanitized.txt")
  dest.write_text(safe,encoding="utf-8")
  results.append({"file":name,"contains_env_credential":matched,"contains_bearer":bearer,"sanitized_copy":str(dest)})
print(json.dumps({"utc":datetime.now(timezone.utc).isoformat(),"credential_values_loaded_without_output":len(secrets),"results":results},ensure_ascii=False,indent=2))

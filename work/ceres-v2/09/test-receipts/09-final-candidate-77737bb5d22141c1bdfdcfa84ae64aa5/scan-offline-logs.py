import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
envfile = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres\.env")
secret_values = []
if envfile.exists():
    for line in envfile.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and re.search(r"(?:API_KEY|TOKEN|SECRET|PASSWORD)", m.group(1), re.I):
            val = m.group(2).strip().strip("\"'").split("#", 1)[0].strip()
            if val:
                secret_values.append(val)
run = Path(sys.argv[1])
reports = []
for stem in ("cold-1-offline-backend-stdout.txt", "cold-1-offline-backend-stderr.txt"):
    source = run / stem
    content = source.read_text(encoding="utf-8", errors="replace")
    credential_match = any(value in content for value in secret_values)
    bearer_match = bool(re.search(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}", content))
    safe = content
    for value in secret_values:
        safe = safe.replace(value, "<REDACTED>")
    safe = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<REDACTED>", safe)
    (run / (stem.replace(".txt", "-sanitized.txt"))).write_text(safe, encoding="utf-8")
    reports.append({"file": stem, "contains_env_credential": credential_match, "contains_bearer": bearer_match, "sanitized_copy": str(run / stem.replace(".txt", "-sanitized.txt"))})
print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "credential_count_loaded_without_output": len(secret_values), "reports": reports}, indent=2))

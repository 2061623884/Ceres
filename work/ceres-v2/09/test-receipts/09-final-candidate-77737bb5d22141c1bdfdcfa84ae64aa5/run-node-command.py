import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
cfg_path=Path(sys.argv[1])
cfg=json.loads(cfg_path.read_text(encoding="utf-8"))
env=os.environ.copy()
for key in cfg.get("unset_env", []):
    env.pop(key, None)
for prefix in cfg.get("unset_prefixes", []):
    for key in list(env):
        if key.startswith(prefix):
            env.pop(key, None)
env.update(cfg.get("env_overrides", {}))
started=datetime.now(timezone.utc)
t0=time.perf_counter()
proc=subprocess.run([cfg["node"], *cfg["argv"]], cwd=cfg["cwd"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
elapsed=time.perf_counter()-t0
ended=datetime.now(timezone.utc)
Path(cfg["stdout_path"]).write_text(proc.stdout, encoding="utf-8")
Path(cfg["stderr_path"]).write_text(proc.stderr, encoding="utf-8")
result={
 "started_utc": started.isoformat(),
 "ended_utc": ended.isoformat(),
 "elapsed_seconds": elapsed,
 "executable": cfg["node"],
 "argv": cfg["argv"],
 "cwd": cfg["cwd"],
 "exit_code": proc.returncode,
 "environment_policy": {"unset_names": cfg.get("unset_env", []), "unset_prefixes": cfg.get("unset_prefixes", []), "overrides": cfg.get("env_overrides", {})},
 "stdout_path": cfg["stdout_path"],
 "stderr_path": cfg["stderr_path"],
}
Path(cfg["result_path"]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(proc.returncode)

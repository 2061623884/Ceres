import datetime, json, pathlib, platform, subprocess, sys, time
out = pathlib.Path(__file__).resolve().parent
remote = "set -eu; repo=/data/amax/services/ceres-kev4b-probe-20261005/upstream; printf 'revision='; git -C \"$repo\" rev-parse HEAD; printf 'matches\\n'; rg -n 'latency_ms|v1/systemone|systemone|create_task|CancelledError|Queue' \"$repo/kev\" \"$repo\"/src 2>/dev/null | head -n 160 || true; printf 'serve_entry\\n'; sed -n '1,240p' \"$repo/kev/serve.py\" 2>/dev/null || true"
argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "amax", remote]
start = datetime.datetime.now(datetime.timezone.utc)
t = time.perf_counter()
r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
rec = {"event":"kev_upstream_request_path_readonly_inspection", "command_argv":argv, "remote_command":remote, "cwd":str(pathlib.Path.cwd()), "python":sys.executable, "started_utc":start.isoformat(), "duration_seconds":round(time.perf_counter()-t,3), "exit_code":r.returncode, "stdout":r.stdout, "stderr":r.stderr}
(out/"upstream-service-code-inspection.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"exit_code":r.returncode,"duration_seconds":rec["duration_seconds"],"stdout":r.stdout,"stderr":r.stderr,"evidence":str(out/"upstream-service-code-inspection.json")},ensure_ascii=False))
raise SystemExit(r.returncode)

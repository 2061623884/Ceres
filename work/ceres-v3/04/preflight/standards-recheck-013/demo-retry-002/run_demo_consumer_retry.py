import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

repo = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres")
run = repo / "work/ceres-v3/04/preflight/standards-recheck-013/demo-retry-002"
scope_path = repo / "work/ceres-v3/04/review-scope.json"
scope = json.loads(scope_path.read_text(encoding="utf-8-sig"))
demo = repo / "work/ceres-v3/03/demo.html"
harness = run / "demo-lifecycle-harness.cjs"
expected_demo = "b2c81bdb621249d72163c20b3b4cc6fcca77929c0a229b28b4512b260ba20026"
expected_zip = "53557616557f773d56020d956aceeb67a0bf5ddac97df6a0672b6b8b8f3657b1"

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def hashes(paths):
    return {p: sha(repo / p) for p in sorted(set(paths))}

node = shutil.which("node")
if not node:
    raise SystemExit("node executable not found")
version = subprocess.run([node, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
if version.returncode:
    raise SystemExit("node --version failed")
before = hashes(scope["paths"])
pre = {
    "review_scope_sha256": sha(scope_path),
    "review_source_zip_sha256": sha(repo / "work/ceres-v3/04/review-source.zip"),
    "expected_review_zip_sha256": expected_zip,
    "demo_sha256": sha(demo), "expected_demo_sha256": expected_demo,
    "scope_hashes_match": all(before[p] == scope["sha256"][p] for p in scope["paths"]),
    "harness_sha256": sha(harness),
}
(run / "pin-check.json").write_text(json.dumps(pre, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if pre["review_source_zip_sha256"] != expected_zip or pre["demo_sha256"] != expected_demo or not pre["scope_hashes_match"]:
    raise SystemExit("review source or demo pin mismatch; consumer not launched")

argv = [node, str(harness), str(demo), str(run)]
command = subprocess.list2cmdline(argv)
(run / "command.txt").write_text(command + "\n", encoding="utf-8")
started = datetime.now(timezone.utc).isoformat()
proc = subprocess.Popen(argv, cwd=run, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
stdout, stderr = proc.communicate()
ended = datetime.now(timezone.utc).isoformat()
(run / "stdout.txt").write_bytes(stdout)
(run / "stderr.txt").write_bytes(stderr)
extracted = run / "inline-script-under-test.js"
syntax_argv = [node, "--check", str(extracted)]
syntax_command = subprocess.list2cmdline(syntax_argv)
(run / "syntax-command.txt").write_text(syntax_command + "\n", encoding="utf-8")
syntax_started = datetime.now(timezone.utc).isoformat()
syntax = subprocess.Popen(syntax_argv, cwd=run, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
syntax_stdout, syntax_stderr = syntax.communicate()
syntax_ended = datetime.now(timezone.utc).isoformat()
(run / "syntax-stdout.txt").write_bytes(syntax_stdout)
(run / "syntax-stderr.txt").write_bytes(syntax_stderr)
after = hashes(scope["paths"])
(run / "source-check-before.json").write_text(json.dumps({"sha256": before}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(run / "source-check-after.json").write_text(json.dumps({"sha256": after, "unchanged": before == after}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
result = {
    "run_id": "04-standards-recheck-013-demo-consumer-retry-002",
    "node_path": node, "node_version": version.stdout.strip(), "pid": proc.pid,
    "temporary_server_started": False, "port": None,
    "started_utc": started, "ended_utc": ended, "command": command,
    "exit_code": proc.returncode,
    "stdout_bytes": len(stdout), "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    "stderr_bytes": len(stderr), "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    "raw_stdout": str(run / "stdout.txt"), "raw_stderr": str(run / "stderr.txt"),
    "syntax_check": {
        "command": syntax_command, "pid": syntax.pid,
        "started_utc": syntax_started, "ended_utc": syntax_ended,
        "exit_code": syntax.returncode,
        "stdout_sha256": hashlib.sha256(syntax_stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(syntax_stderr).hexdigest(),
        "raw_stdout": str(run / "syntax-stdout.txt"), "raw_stderr": str(run / "syntax-stderr.txt"),
        "checked_file": str(extracted), "checked_file_sha256": sha(extracted),
    },
    "demo_source_sha256_before": pre["demo_sha256"], "demo_source_sha256_after": sha(demo),
    "scope_hashes_unchanged": before == after,
    "harness_sha256": pre["harness_sha256"], "mocked_api_dom_consumer": True,
    "browser_e2e": False, "live_backend_or_model": False,
}
(run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
if proc.returncode:
    raise SystemExit(proc.returncode)
if syntax.returncode:
    raise SystemExit(syntax.returncode)

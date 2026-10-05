import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

repo = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres")
backend = repo / "backend"
run = repo / "work/ceres-v3/04/preflight/standards-recheck-013/api-lifecycle"
scope_path = repo / "work/ceres-v3/04/review-scope.json"
scope = json.loads(scope_path.read_text(encoding="utf-8-sig"))
expected_zip = "53557616557f773d56020d956aceeb67a0bf5ddac97df6a0672b6b8b8f3657b1"
expected_demo = "b2c81bdb621249d72163c20b3b4cc6fcca77929c0a229b28b4512b260ba20026"

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def file_hashes(paths):
    return {path: sha(repo / path) for path in sorted(set(paths))}

scope_hash = sha(scope_path)
zip_hash = sha(repo / "work/ceres-v3/04/review-source.zip")
demo_hash = sha(repo / "work/ceres-v3/03/demo.html")
before = file_hashes(scope["paths"])
precheck = {
    "scope_sha256": scope_hash,
    "review_source_zip_expected": expected_zip,
    "review_source_zip_actual": zip_hash,
    "demo_expected_sha256": expected_demo,
    "demo_actual_sha256": demo_hash,
    "source_hashes_match_review_scope": all(before[p] == scope["sha256"][p] for p in scope["paths"]),
}
(run / "pin-check.json").write_text(json.dumps(precheck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if zip_hash != expected_zip or demo_hash != expected_demo or not precheck["source_hashes_match_review_scope"]:
    raise SystemExit("Frozen source pin mismatch; test not launched")

test_support = json.loads((repo / "work/ceres-v3/04/preflight/green-005/environment-and-source.json").read_text(encoding="utf-8-sig"))
paths = list(dict.fromkeys([*scope["paths"], *test_support["sha256_before"].keys()]))
before = file_hashes(paths)
temp = run / "os-temp"
basetemp = run / "pytest-tmp"
executable = backend / ".venv/Scripts/python.exe"
node = "tests/test_v3_switch_lifecycle.py::test_display_quota_survives_get_rejection_and_role_switch_until_explicit_close"
argv = [str(executable), "-X", "utf8", "-m", "pytest", "-q", "--showlocals", "-p", "no:cacheprovider", "-W", "error::pytest.PytestUnhandledThreadExceptionWarning", f"--basetemp={basetemp}", node]
command = subprocess.list2cmdline(argv)
(run / "command.txt").write_text(command + "\n", encoding="utf-8")

env = os.environ.copy()
env.update({
    "TEMP": str(temp), "TMP": str(temp), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
    "LLM_MODE": "live", "BUSINESS_DATA_MODE": "demo",
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_API_KEY": "codex-test-only-public",
    "LLM_MODEL": "codex-test-model", "MEMORY_MODEL": "", "KEV_BASE_URL": "http://127.0.0.1:9",
    "RETRIEVAL_MODE": "hybrid", "RETRIEVAL_INDEX_DIR": "",
    "EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1", "EMBEDDING_API_KEY": "codex-test-only-public",
    "EMBEDDING_MODEL": "codex-test-embedding", "EMBEDDING_REVISION": "standards-recheck-fixed",
    "EMBEDDING_DIMENSION": "1024", "SOURCE_DATABASE_PATH": str(repo / "data/sale_guide.db"),
    "DATABASE_URL": f"sqlite:///{(run / 'runtime.sqlite3').as_posix()}",
    "MERCURY_DB_PATH": str(run / "mercury.sqlite3"),
})
started = datetime.now(timezone.utc).isoformat()
proc = subprocess.Popen(argv, cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
stdout, stderr = proc.communicate()
ended = datetime.now(timezone.utc).isoformat()
(run / "stdout.txt").write_bytes(stdout)
(run / "stderr.txt").write_bytes(stderr)
after = file_hashes(paths)
(run / "source-check-before.json").write_text(json.dumps({"sha256": before}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(run / "source-check-after.json").write_text(json.dumps({"sha256": after, "unchanged": before == after}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
versions = subprocess.run([str(executable), "-X", "utf8", "-c", "import sys,pytest; print(sys.version); print('pytest', pytest.__version__)"], cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
environment = {
    "run_id": "04-standards-recheck-013-api-lifecycle",
    "cwd": str(backend), "executable": str(executable), "python_and_pytest_version": versions.stdout.strip().splitlines(),
    "argv": argv, "command": command, "working_directory": str(backend),
    "TEMP": str(temp), "TMP": str(temp), "pytest_basetemp": str(basetemp),
    "warning_filter": "error::pytest.PytestUnhandledThreadExceptionWarning", "pytest_cacheprovider": "disabled",
    "MEMORY_MODEL": "", "RETRIEVAL_INDEX_DIR": "empty process default; indexed_client fixture sets per-test lexical index bound to its temporary DB",
    "controlled_environment": {
        "LLM_MODE": env["LLM_MODE"], "BUSINESS_DATA_MODE": env["BUSINESS_DATA_MODE"],
        "OPENAI_BASE_URL": env["OPENAI_BASE_URL"], "OPENAI_API_KEY": "public dummy literal, no credential",
        "LLM_MODEL": env["LLM_MODEL"], "KEV_BASE_URL": env["KEV_BASE_URL"],
        "RETRIEVAL_MODE": env["RETRIEVAL_MODE"], "EMBEDDING_BASE_URL": env["EMBEDDING_BASE_URL"],
        "EMBEDDING_API_KEY": "public dummy literal, no credential", "EMBEDDING_MODEL": env["EMBEDDING_MODEL"],
        "EMBEDDING_REVISION": env["EMBEDDING_REVISION"], "EMBEDDING_DIMENSION": env["EMBEDDING_DIMENSION"],
        "SOURCE_DATABASE_PATH": env["SOURCE_DATABASE_PATH"], "DATABASE_URL": "overridden by isolated test_db_url fixture",
        "MERCURY_DB_PATH": env["MERCURY_DB_PATH"],
    },
    "database_isolation": "indexed_client uses pytest temporary SQLite DB with paired per-test lexical index; Mercury DB path is run-local",
    "network_scope": "Controlled Kev, semantic, and Mercury fixtures; MEMORY_MODEL empty; dummy loopback API configuration. No complete outbound capture performed.",
    "test": node, "source_paths": paths, "pin_check": precheck,
}
(run / "environment-and-source.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
result = {
    "run_id": environment["run_id"], "pid": proc.pid, "started_utc": started, "ended_utc": ended,
    "exit_code": proc.returncode, "stdout_bytes": len(stdout), "stderr_bytes": len(stderr),
    "stdout_sha256": hashlib.sha256(stdout).hexdigest(), "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    "source_hashes_unchanged": before == after, "versions_exit_code": versions.returncode,
    "raw_stdout": str(run / "stdout.txt"), "raw_stderr": str(run / "stderr.txt"),
}
(run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(proc.returncode)

import hashlib
import json
import re
import subprocess
from pathlib import Path

root = Path.cwd()
def run(args, cwd=root):
    p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"command": args, "exit_code": p.returncode,
            "stdout": p.stdout.decode("utf-8", errors="replace"),
            "stderr": p.stderr.decode("utf-8", errors="replace")}
def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()
def digest_path(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def staged_blob(path):
    return run(["git", "show", f":{path}"])
def git_path_bytes(path):
    p = subprocess.run(["git", "show", f":{path}"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f"cannot read index blob for {path}: {p.stderr.decode(errors='replace')}")
    return p.stdout
def numstat(args):
    result = run(args)
    if result["exit_code"] != 0:
        return {**result, "parsed": None}
    line = result["stdout"].strip()
    if not line:
        return {**result, "parsed": {"added": 0, "deleted": 0, "path": None}}
    added, deleted, path = line.split("\t", 2)
    return {**result, "parsed": {"added": int(added), "deleted": int(deleted), "path": path}}
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

repo = run(["git", "rev-parse", "--show-toplevel"])
stage = run(["git", "diff", "--cached", "--name-only", "-z"])
staged_paths = [p for p in stage["stdout"].split("\x00") if p]
stage_check = run(["git", "diff", "--cached", "--check"])
cached_readme = numstat(["git", "diff", "--cached", "--numstat", "--", "README.md"])
unstaged_readme = numstat(["git", "diff", "--numstat", "--", "README.md"])
cached_readme_patch = run(["git", "diff", "--cached", "--", "README.md"])
unstaged_readme_patch = run(["git", "diff", "--", "README.md"])
candidate = root / "work/.ceres-next-08"
candidate_head = run(["git", "-C", str(candidate), "rev-parse", "HEAD"])
candidate_diff = run(["git", "-C", str(candidate), "diff", "HEAD", "--quiet"])
candidate_status = run(["git", "-C", str(candidate), "status", "--short", "--untracked-files=no"])
expected_head = "ac895fd620af617fa31f4e0006841a4d6a89cd53"

task_files = {
    "tasks/ceres-v4-evaluation.md",
    "tasks/ceres-v4-evaluation-01-core-pilot.md",
    "tasks/ceres-v4-evaluation-02-full-task-evaluation.md",
    "tasks/ceres-v4-evaluation-03-browser-journeys.md",
    "tasks/ceres-v4-evaluation-04-acceptance-record.md",
    "tasks/ceres-v4-repair-aftersales.md",
    "tasks/ceres-v4-repair-latency.md",
    "tasks/ceres-v4-repair-memory.md",
    "tasks/ceres-v4-repair-shopping.md",
}
script_files = {
    "scripts/.gitattributes",
    "scripts/eval_v4.py",
    "scripts/eval_v4_judge.py",
    "scripts/eval_v4_record.py",
    "scripts/eval_v4_ui.mjs",
    "scripts/test_eval_v4.py",
}
exact = {"README.md", "docs/plans/ceres-v4-evaluation-spec.md",
         "logs/ceres-v4-evaluation.md"} | task_files | script_files
def allowed(path):
    return path in exact or path.startswith("evals/v4/") or path.startswith("work/ceres-v4-evaluation/")
unexpected = sorted(path for path in staged_paths if not allowed(path))
missing_required = sorted(path for path in exact if path not in staged_paths)
forbidden_pattern = re.compile(r"(^|/)(\.env(?:\..*)?|__pycache__|cache)(/|$)|\.(?:sqlite3?|db|pyc)$|(?:-wal|-shm)$", re.I)
forbidden = sorted(path for path in staged_paths if forbidden_pattern.search(path))

source_snapshots = {
    "scripts/eval_v4.py": "work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4.py.frozen.py",
    "scripts/test_eval_v4.py": "work/ceres-v4-evaluation/evidence/rescore-run04/test_eval_v4.py.frozen.py",
    "scripts/eval_v4_judge.py": "work/ceres-v4-evaluation/evidence/diag-run03-v3/eval_v4_judge.frozen.py",
    "scripts/eval_v4_record.py": "work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4_record.py.final-frozen.py",
    "scripts/eval_v4_ui.mjs": "work/ceres-v4-evaluation/evidence/rescore-run04/eval_v4_ui.current.frozen.mjs",
    "evals/v4/cases.json": "work/ceres-v4-evaluation/evidence/rescore-run04/cases.v2.frozen.json",
}
hash_rows = []
for source, snapshot in source_snapshots.items():
    current_hash = digest_path(root / source)
    snapshot_hash = digest_path(root / snapshot)
    index_bytes = git_path_bytes(source)
    index_hash = digest_bytes(index_bytes)
    hash_rows.append({"path": source, "current_sha256": current_hash, "frozen_sha256": snapshot_hash,
                      "staged_index_blob_sha256": index_hash,
                      "current_matches_frozen": current_hash == snapshot_hash,
                      "staged_matches_frozen": index_hash == snapshot_hash})
acceptance = read_json(root / "work/ceres-v4-evaluation/acceptance/acceptance.json")
run04_manifest = read_json(root / "work/ceres-v4-evaluation/run-04/manifest.json")
record_hashes = {
    "acceptance_reporter_sha256": acceptance["reporter_sha256"],
    "current_record_script_sha256": digest_path(root / "scripts/eval_v4_record.py"),
    "staged_record_script_sha256": next(row["staged_index_blob_sha256"] for row in hash_rows if row["path"] == "scripts/eval_v4_record.py"),
    "run04_runner_sha256": run04_manifest["runner_sha256"],
    "current_eval_runner_sha256": digest_path(root / "scripts/eval_v4.py"),
    "run04_cases_sha256": run04_manifest["cases_sha256"],
    "current_cases_sha256": digest_path(root / "evals/v4/cases.json"),
}
staged_assets = []
for path in staged_paths:
    suffix = Path(path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".zip"}:
        continue
    raw = git_path_bytes(path)
    attrs = run(["git", "check-attr", "--cached", "filter", "--", path])
    text = raw.decode("ascii", errors="replace")
    is_pointer = (raw.startswith(b"version https://git-lfs.github.com/spec/v1\n")
                  and re.search(r"(?m)^oid sha256:[0-9a-f]{64}$", text)
                  and re.search(r"(?m)^size [0-9]+$", text))
    oid_match = re.search(r"(?m)^oid sha256:([0-9a-f]{64})$", text)
    size_match = re.search(r"(?m)^size ([0-9]+)$", text)
    filter_lfs = "filter: lfs" in attrs["stdout"]
    staged_assets.append({"path": path, "staged_blob_bytes": len(raw), "lfs_pointer": bool(is_pointer),
                          "filter_lfs": filter_lfs, "pointer_oid_sha256": oid_match.group(1) if oid_match else None,
                          "pointer_payload_size": int(size_match.group(1)) if size_match else None,
                          "attributes_command": attrs})

tasks_staged = sorted(path for path in staged_paths if path.startswith("tasks/"))
readme_ok = cached_readme["parsed"] == {"added": 1, "deleted": 0, "path": "README.md"} and unstaged_readme["parsed"] == {"added": 7, "deleted": 0, "path": "README.md"}
hashes_ok = all(row["current_matches_frozen"] and row["staged_matches_frozen"] for row in hash_rows)
report_hash_ok = (record_hashes["acceptance_reporter_sha256"] == record_hashes["current_record_script_sha256"]
                  == record_hashes["staged_record_script_sha256"])
runner_hash_ok = record_hashes["run04_runner_sha256"] == record_hashes["current_eval_runner_sha256"]
cases_hash_ok = record_hashes["run04_cases_sha256"] == record_hashes["current_cases_sha256"]
lfs_ok = all(row["lfs_pointer"] and row["filter_lfs"] for row in staged_assets)
candidate_ok = (candidate_head["stdout"].strip() == expected_head and candidate_diff["exit_code"] == 0
                and candidate_status["stdout"].strip() == "")
result = {
    "repo_root": repo["stdout"].strip(),
    "staged_count": len(staged_paths),
    "staged_paths_file": "staged-paths.txt",
    "task_paths_count": len(tasks_staged),
    "task_paths": tasks_staged,
    "allowed_scope": {"unexpected_paths": unexpected, "missing_required_exact_paths": missing_required,
                      "forbidden_secret_db_cache_paths": forbidden},
    "git_diff_cached_check": stage_check,
    "README": {"cached_numstat": cached_readme, "unstaged_numstat": unstaged_readme,
               "cached_patch": cached_readme_patch, "unstaged_patch": unstaged_readme_patch,
               "cached_one_line_only_and_original_seven_unstaged": readme_ok},
    "candidate": {"head": candidate_head["stdout"].strip(), "expected_head": expected_head,
                  "tracked_diff": candidate_diff, "tracked_status": candidate_status, "clean": candidate_ok},
    "source_hashes": hash_rows,
    "acceptance_and_manifest_hashes": record_hashes,
    "hash_gates": {"all_source_and_case_staged_blobs_match_frozen": hashes_ok,
                   "acceptance_reporter_matches_current_and_staged": report_hash_ok,
                   "run04_runner_hash_matches_staged_current_script": runner_hash_ok,
                   "run04_case_hash_matches_staged_current_cases": cases_hash_ok},
    "lfs_assets": staged_assets,
    "lfs_assets_all_index_pointers_with_lfs_filter": lfs_ok,
}
result["overall_pass"] = (
    not unexpected and not missing_required and not forbidden
    and stage_check["exit_code"] == 0
    and readme_ok and candidate_ok and hashes_ok and report_hash_ok and runner_hash_ok and cases_hash_ok and lfs_ok
)
print(json.dumps(result, ensure_ascii=False, indent=2))

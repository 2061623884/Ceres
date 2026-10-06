"""One-shot, read-only precommit verifier for Ceres V3 publication evidence."""

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[4]
TASK_ROOT = ROOT / "work" / "ceres-v3" / "07"

parser = argparse.ArgumentParser()
parser.add_argument("--scope-manifest", type=Path, required=True,
                    help="JSON array or {expected_staged_paths: [...]} supplied after final staging scope is approved")
parser.add_argument("--output-dir", type=Path, required=True,
                    help="New run-specific directory under work/ceres-v3/07")
args = parser.parse_args()

scope_path = args.scope_manifest.resolve()
output_dir = args.output_dir.resolve()
if not output_dir.is_relative_to(TASK_ROOT.resolve()):
    raise ValueError("output-dir must remain under work/ceres-v3/07")
output_dir.mkdir(parents=True, exist_ok=False)

started_utc = datetime.now(timezone.utc).isoformat()
execution_record = {
    "process_id": os.getpid(),
    "started_utc": started_utc,
    "executable": sys.executable,
    "argv": sys.argv,
    "cwd": str(Path.cwd()),
    "scope_manifest": str(scope_path),
    "output_dir": str(output_dir),
    "environment": {
        "PYTHONUTF8": os.environ.get("PYTHONUTF8"),
        "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
        "LLM_MODE": "not used by checker",
        "model_calls_made": False,
    },
}
(output_dir / "checker-start.json").write_text(
    json.dumps(execution_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

errors = []
checks = {}

baseline_path = TASK_ROOT / "candidate-v5" / "baseline.json"
delta_path = TASK_ROOT / "publication-delta.json"
raw_manifest_path = TASK_ROOT / "retained-raw-manifest.json"
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
publication_delta = json.loads(delta_path.read_text(encoding="utf-8"))

# Record one real git diff --cached --check process with its own stdout/stderr.
git_check_argv = ["git", "diff", "--cached", "--check"]
git_env = os.environ.copy()
git_env_summary = {
    name: git_env.get(name)
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_OPTIONAL_LOCKS", "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
    )
}
git_check_started = datetime.now(timezone.utc).isoformat()
git_check_process = subprocess.Popen(
    git_check_argv, cwd=ROOT, env=git_env,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
git_stdout, git_stderr = git_check_process.communicate()
git_check_ended = datetime.now(timezone.utc).isoformat()
(output_dir / "git-diff-cached-check.stdout.raw.txt").write_bytes(git_stdout)
(output_dir / "git-diff-cached-check.stderr.raw.txt").write_bytes(git_stderr)
git_check_record = {
    "argv": git_check_argv,
    "cwd": str(ROOT),
    "process_id": git_check_process.pid,
    "started_utc": git_check_started,
    "ended_utc": git_check_ended,
    "exit_code": git_check_process.returncode,
    "environment": git_env_summary,
    "credential_values_recorded": False,
    "stdout_path": "git-diff-cached-check.stdout.raw.txt",
    "stderr_path": "git-diff-cached-check.stderr.raw.txt",
}
(output_dir / "git-diff-cached-check.process.json").write_text(
    json.dumps(git_check_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
checks["git_diff_cached_check"] = {
    "exit_code": git_check_process.returncode,
    "stdout_bytes": len(git_stdout),
    "stderr_bytes": len(git_stderr),
}
if git_check_process.returncode != 0:
    errors.append({"check": "git_diff_cached_check", "message": "git diff --cached --check returned nonzero"})

# Verify byte-preserving copies in retained-raw-manifest.json.
raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
raw_entries = raw_manifest["entries"]
raw_root = TASK_ROOT / "retained-raw"
representations = {"utf8_text": 0, "base64_bytes": 0}
raw_failures = []
seen_sources = set()
seen_retained = set()
for entry in raw_entries:
    source_rel = entry["source"]
    retained_rel = PurePosixPath(entry["retained"])
    if retained_rel.is_absolute() or ".." in retained_rel.parts:
        raw_failures.append({"retained": entry["retained"], "error": "retained path escapes task root"})
        continue
    if source_rel in seen_sources or entry["retained"] in seen_retained:
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": "duplicate manifest entry"})
        continue
    seen_sources.add(source_rel)
    seen_retained.add(entry["retained"])
    retained_file = TASK_ROOT.joinpath(*retained_rel.parts)
    if not retained_file.is_file():
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": "retained record missing"})
        continue
    record = json.loads(retained_file.read_text(encoding="utf-8"))
    if record.get("original_path") != source_rel:
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": "original_path mismatch"})
        continue
    if record.get("bytes") != entry["bytes"] or record.get("sha256") != entry["sha256"]:
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": "record metadata differs from manifest"})
        continue
    has_utf8 = "utf8_text" in record
    has_base64 = "base64_bytes" in record
    if has_utf8 == has_base64:
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": "expected exactly one raw-byte representation"})
        continue
    try:
        if has_utf8:
            original_bytes = record["utf8_text"].encode("utf-8")
            representations["utf8_text"] += 1
        else:
            original_bytes = base64.b64decode(record["base64_bytes"], validate=True)
            representations["base64_bytes"] += 1
    except (UnicodeEncodeError, binascii.Error, TypeError, ValueError) as exc:
        raw_failures.append({"source": source_rel, "retained": entry["retained"], "error": f"raw representation decode failed: {type(exc).__name__}: {exc}"})
        continue
    actual_sha = hashlib.sha256(original_bytes).hexdigest()
    if len(original_bytes) != entry["bytes"] or actual_sha != entry["sha256"]:
        raw_failures.append({
            "source": source_rel,
            "retained": entry["retained"],
            "expected_bytes": entry["bytes"],
            "actual_bytes": len(original_bytes),
            "expected_sha256": entry["sha256"],
            "actual_sha256": actual_sha,
        })
retained_disk_paths = {
    "retained-raw/" + path.name for path in raw_root.glob("*.json")
}
if retained_disk_paths != seen_retained:
    raw_failures.append({
        "error": "retained-raw directory and manifest entry set differ",
        "unlisted_files": sorted(retained_disk_paths - seen_retained),
        "missing_files": sorted(seen_retained - retained_disk_paths),
    })
if len(raw_entries) != 193:
    raw_failures.append({"error": "retained raw manifest count is not 193", "actual_count": len(raw_entries)})
checks["retained_raw"] = {
    "manifest_entry_count": len(raw_entries),
    "representation_counts": representations,
    "checked_count": sum(representations.values()),
    "failure_count": len(raw_failures),
    "failures": raw_failures,
}
if raw_failures:
    errors.append({"check": "retained_raw", "message": f"{len(raw_failures)} retained-raw verification failures"})

# Compare the current 312-path source tree with v5 plus the declared three publication edits.
frozen_hashes = baseline["sha256"]
publication_changes = publication_delta["publication_only_changes"]
published_by_path = {item["path"]: item for item in publication_changes}
expected_publication_paths = set(publication_delta["expected_publication_paths"])
declared_publication_paths = set(published_by_path)
source_failures = []
actual_hashes = {}
changed_since_v5 = []
if len(frozen_hashes) != 312 or publication_delta["compared_paths"] != 312:
    source_failures.append({"error": "source path count is not 312", "baseline_count": len(frozen_hashes), "delta_count": publication_delta["compared_paths"]})
if len(publication_changes) != 3 or declared_publication_paths != expected_publication_paths:
    source_failures.append({"error": "publication delta does not declare exactly its expected three paths"})
if publication_delta["tested_zip_sha256"] != baseline["source_zip_sha256"]:
    source_failures.append({"error": "publication delta tested ZIP differs from candidate-v5"})
if publication_delta["tested_head"] != baseline["git_head"]:
    source_failures.append({"error": "publication delta tested HEAD differs from candidate-v5"})
for relative_path, frozen_sha in frozen_hashes.items():
    current_path = ROOT / Path(*PurePosixPath(relative_path).parts)
    current_sha = hashlib.sha256(current_path.read_bytes()).hexdigest()
    actual_hashes[relative_path] = current_sha
    if current_sha != frozen_sha:
        changed_since_v5.append(relative_path)
    if relative_path in published_by_path:
        publication_item = published_by_path[relative_path]
        if frozen_sha != publication_item["tested_sha256"]:
            source_failures.append({"path": relative_path, "error": "publication tested hash differs from v5 baseline"})
        expected_current_sha = publication_item["published_sha256"]
    else:
        expected_current_sha = frozen_sha
    if current_sha != expected_current_sha:
        source_failures.append({
            "path": relative_path,
            "expected_sha256": expected_current_sha,
            "actual_sha256": current_sha,
        })
if set(changed_since_v5) != declared_publication_paths:
    source_failures.append({
        "error": "paths changed since v5 are not exactly the declared publication edits",
        "changed_since_v5": sorted(changed_since_v5),
        "declared_publication_paths": sorted(declared_publication_paths),
    })
catalog_path = ROOT / "data" / "sale_guide.db"
catalog_sha = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
if catalog_sha != baseline["source_catalog"]["sha256"] or catalog_sha != publication_delta["catalog_sha256"]:
    source_failures.append({"error": "catalog SHA differs from tested v5/publication delta", "actual_sha256": catalog_sha})
zip_path = TASK_ROOT / "candidate-v5" / "source.zip"
zip_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
if zip_sha != baseline["source_zip_sha256"]:
    source_failures.append({"error": "candidate-v5 source ZIP changed", "actual_sha256": zip_sha})
unchanged_families = {}
family_prefixes = {
    "runtime": ("backend/app/", "Mercury/"),
    "tests": ("backend/tests/", "Mercury/tests/"),
    "data": ("data/",),
    "prompts": ("backend/app/prompts/",),
    "cases": ("evals/",),
    "demo_or_frontend": ("frontend/", "work/ceres-v3/03/", "work/ceres-v3/04/"),
}
for family, prefixes in family_prefixes.items():
    family_paths = [path for path in frozen_hashes if path.startswith(prefixes)]
    family_changes = [path for path in family_paths if actual_hashes[path] != frozen_hashes[path]]
    unchanged_families[family] = {
        "path_count": len(family_paths),
        "changed_since_v5": family_changes,
    }
    if family_changes:
        source_failures.append({"family": family, "error": "non-publication family changed since v5", "paths": family_changes})
checks["publication_source"] = {
    "candidate_zip_sha256": zip_sha,
    "tested_head": baseline["git_head"],
    "source_path_count": len(frozen_hashes),
    "changed_since_v5": sorted(changed_since_v5),
    "publication_paths": sorted(declared_publication_paths),
    "catalog_sha256": catalog_sha,
    "unchanged_families": unchanged_families,
    "failure_count": len(source_failures),
    "failures": source_failures,
}
if source_failures:
    errors.append({"check": "publication_source", "message": f"{len(source_failures)} publication/source verification failures"})

# Compare the staged index to the final scope manifest and reject artifacts that must stay local.
scope_data = json.loads(scope_path.read_text(encoding="utf-8"))
expected_staged = scope_data if isinstance(scope_data, list) else scope_data["expected_staged_paths"]
if not isinstance(expected_staged, list) or any(not isinstance(path, str) for path in expected_staged):
    raise ValueError("scope manifest must be a JSON string array or contain expected_staged_paths")
expected_paths = [path.replace("\\", "/").removeprefix("./") for path in expected_staged]
if len(expected_paths) != len(set(expected_paths)):
    errors.append({"check": "staged_scope", "message": "scope manifest contains duplicate paths"})
staged_result = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z"], cwd=ROOT,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
)
staged_paths = [path for path in staged_result.stdout.decode("utf-8").split("\0") if path]
staged_set = set(staged_paths)
expected_set = set(expected_paths)
scope_missing = sorted(expected_set - staged_set)
scope_extra = sorted(staged_set - expected_set)
if scope_missing or scope_extra:
    errors.append({"check": "staged_scope", "message": "staged paths differ from approved scope manifest", "missing": scope_missing, "extra": scope_extra})

forbidden_paths = []
for path in staged_paths:
    normalized = path.replace("\\", "/").strip("/")
    lowered = normalized.lower()
    parts = lowered.split("/")
    reason = None
    if lowered in {
        "backend/tests/test_p0_gap_persistence.py",
        "backend/tests/test_w_dish_and_gap.py",
    }:
        reason = "inherited gap test file is excluded"
    elif any(part == ".env" or part.startswith(".env.") for part in parts):
        reason = ".env file is excluded"
    elif lowered.startswith("frontend/src/"):
        reason = "frontend/src is outside this ticket's publication scope"
    elif lowered.endswith((".zip", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".safetensors", ".gguf", ".pt", ".pth", ".onnx", ".bin", ".faiss", ".idx", ".index", ".tmp", ".temp")):
        reason = "archive, database, or model weight is excluded"
    elif any(part in {"weights", "checkpoints", "retrieval_index", "retrieval-index", "index", "indexes"} for part in parts):
        reason = "weights, checkpoint, or retrieval index is excluded"
    elif any(part in {"tmp", "temp", "basetemp", ".pytest_cache", "__pycache__"} or "basetemp" in part or "pytest-of-" in part or part.endswith("-temp") for part in parts):
        reason = "temporary test/runtime artifact is excluded"
    if reason:
        forbidden_paths.append({"path": path, "reason": reason})
if forbidden_paths:
    errors.append({"check": "staged_scope", "message": "forbidden staged artifacts found", "paths": forbidden_paths})

# Require exactly one newly added Ceres V3 entry in the staged README index.
readme_entry_pattern = re.compile(r"^\s*-\s+\[Ceres V3 TASK\]", re.IGNORECASE)
readme_added_v3_entries = []
readme_staged_entry_count = None
readme_head_entry_count = None
if "README.md" not in staged_set:
    errors.append({"check": "readme_index", "message": "README.md is not staged"})
else:
    staged_readme = subprocess.run(["git", "show", ":README.md"], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode("utf-8")
    head_readme = subprocess.run(["git", "show", "HEAD:README.md"], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode("utf-8")
    readme_diff = subprocess.run(["git", "diff", "--cached", "--unified=0", "--", "README.md"], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode("utf-8")
    readme_added_v3_entries = [
        line[1:] for line in readme_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++") and readme_entry_pattern.search(line[1:])
    ]
    readme_staged_entry_count = sum(bool(readme_entry_pattern.search(line)) for line in staged_readme.splitlines())
    readme_head_entry_count = sum(bool(readme_entry_pattern.search(line)) for line in head_readme.splitlines())
    readme_ok = (
        len(readme_added_v3_entries) == 1
        and readme_staged_entry_count == 1
        and readme_staged_entry_count - readme_head_entry_count == 1
    )
    if not readme_ok:
        errors.append({
            "check": "readme_index",
            "message": "expected exactly one newly added Ceres V3 TASK index entry",
            "added_v3_entries": readme_added_v3_entries,
            "staged_v3_entry_count": readme_staged_entry_count,
            "head_v3_entry_count": readme_head_entry_count,
        })
checks["staged_scope"] = {
    "scope_manifest": str(scope_path),
    "expected_count": len(expected_paths),
    "staged_count": len(staged_paths),
    "missing": scope_missing,
    "extra": scope_extra,
    "forbidden_paths": forbidden_paths,
}
checks["readme_index"] = {
    "added_v3_entries": readme_added_v3_entries,
    "staged_v3_entry_count": readme_staged_entry_count,
    "head_v3_entry_count": readme_head_entry_count,
    "passed": len(readme_added_v3_entries) == 1 and readme_staged_entry_count == 1
              and readme_staged_entry_count - readme_head_entry_count == 1,
}

result = {
    "candidate": {
        "version": baseline["candidate_version"],
        "zip_sha256": baseline["source_zip_sha256"],
        "head": baseline["git_head"],
    },
    "checks": checks,
    "errors": errors,
    "passed": not errors,
}
(output_dir / "precommit-summary.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
exit_code = 0 if not errors else 1
execution_record["ended_utc"] = datetime.now(timezone.utc).isoformat()
execution_record["exit_code"] = exit_code
(output_dir / "checker-exit.json").write_text(
    json.dumps(execution_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({"passed": result["passed"], "error_count": len(errors), "output_dir": str(output_dir)}, ensure_ascii=False))
raise SystemExit(exit_code)

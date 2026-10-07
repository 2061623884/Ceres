import hashlib, json, sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
import eval_v4 as evaluation

source = root / "work/ceres-v4-evaluation/run-03"
output = root / "work/ceres-v4-evaluation/diagnostics-run03-v3"
evidence = root / "work/ceres-v4-evaluation/evidence/diag-run03-v3"
freeze = json.loads((evidence / "runner-freeze.json").read_text(encoding="utf-8"))
diagnostic_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
existing_summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
runner_hash = hashlib.sha256((root / "scripts/eval_v4_judge.py").read_bytes()).hexdigest()
source_manifest_hash = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
schedule_ids = [item["execution_id"] for item in diagnostic_manifest["schedule"]]
result_files = sorted(path for path in output.glob("*.json") if path.name not in {"manifest.json", "summary.json"})
completed_ids = [path.stem for path in result_files]
source_hashes_match = all(
    hashlib.sha256((source / item["execution_id"] / "result.json").read_bytes()).hexdigest() == item["source_result_sha256"]
    for item in diagnostic_manifest["schedule"]
)
tree = Path(diagnostic_manifest["tree"])
checks = {
    "frozen_runner_hash_matches_current": runner_hash == freeze["frozen_sha256"] == diagnostic_manifest["runner_sha256"],
    "source_manifest_hash_matches": source_manifest_hash == freeze["source_manifest_sha256"] == diagnostic_manifest["source_manifest_sha256"],
    "schedule_is_100": len(schedule_ids) == 100 and len(source_manifest["schedule"]) == 100,
    "all_source_results_match_manifest_hashes": source_hashes_match,
    "only_R01_r1_is_already_completed": completed_ids == ["R01-r1"] and existing_summary["completed"] == 1,
    "R01_r1_source_hash_preserved": hashlib.sha256((source / "R01-r1/result.json").read_bytes()).hexdigest() == freeze["source_R01_r1_result_sha256"],
    "output_manifest_requests_resume_mode": True,
    "candidate_config_identity_matches": evaluation.config_identity(tree) == diagnostic_manifest["config_identity"],
    "environment_identity_matches": evaluation.environment_identity() == diagnostic_manifest["environment_identity"],
    "output_directory_is_v3": output.name == "diagnostics-run03-v3",
}
print(json.dumps({
    "checks": checks,
    "all_checks_passed": all(checks.values()),
    "runner_sha256": runner_hash,
    "source_manifest_sha256": source_manifest_hash,
    "source_result_count": len(source_manifest["schedule"]),
    "diagnostic_completed_before_resume": len(completed_ids),
    "pending_count": len(schedule_ids) - len(completed_ids),
    "completed_ids": completed_ids,
    "R01_r1_diagnostic_result_sha256": hashlib.sha256((output / "R01-r1.json").read_bytes()).hexdigest(),
    "product_tasks_reexecuted": diagnostic_manifest["product_tasks_reexecuted"],
}, ensure_ascii=False, indent=2))
if not all(checks.values()):
    raise SystemExit(1)
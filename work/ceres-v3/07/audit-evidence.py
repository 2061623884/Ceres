"""Read raw execution records and source provenance; never execute a test."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--layout", choices=("group-v4", "flat-v5"), default="group-v4")
parser.add_argument("runs", nargs="+")
args = parser.parse_args()
baseline_path = Path(args.baseline)
baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
zip_path = baseline_path.parent / "source.zip"
report = {
    "at": datetime.now(timezone.utc).isoformat(),
    "purpose": "Primary-agent raw-record and provenance audit, not a test run",
    "baseline": str(baseline_path),
    "expected_zip_sha256": baseline["source_zip_sha256"],
    "actual_zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    "actual_results": [],
}
for run_text in args.runs:
    run = Path(run_text)
    if args.layout == "group-v4":
        command_name, completion_name = "command-environment.json", "process-completion.json"
        stdout_name, stderr_name = "stdout.txt", "stderr.txt"
        raw_names = (command_name, "process-start.json", completion_name, "source-before.json", "source-after.json", stdout_name, stderr_name)
    else:
        command_name, completion_name = "process-start.json", "process-exit.json"
        stdout_name, stderr_name = "stdout.raw.txt", "stderr.raw.txt"
        raw_names = (command_name, completion_name, "source-before.json", "source-after.json", stdout_name, stderr_name)
    command = json.loads((run / command_name).read_text(encoding="utf-8-sig"))
    completion = json.loads((run / completion_name).read_text(encoding="utf-8-sig"))
    item = {
        "run": str(run),
        "command": command,
        "completion": completion,
        "source": [],
        "raw": {},
        "stdout_tail": (run / stdout_name).read_text(encoding="utf-8-sig").splitlines()[-10:],
        "stderr": (run / stderr_name).read_text(encoding="utf-8-sig"),
    }
    for name in ("source-before.json", "source-after.json"):
        source = json.loads((run / name).read_text(encoding="utf-8-sig"))
        observed = source["source_sha256" if args.layout == "group-v4" else "hashes"]
        item["source"].append({
            "file": name,
            "paths": len(observed),
            "expected_paths": len(baseline["sha256"]),
            "changed_or_missing": [p for p, digest in baseline["sha256"].items() if observed.get(p) != digest],
            "extra": sorted(set(observed) - set(baseline["sha256"])),
            "zip": source["source_zip_sha256"] if args.layout == "group-v4" else source.get("candidate_zip_sha256"),
            "zip_note": "ZIP hash not reported in this source-after record; path hashes compared to baseline" if args.layout == "flat-v5" and "candidate_zip_sha256" not in source else "reported by executor",
            "head": source["git_head"],
            "catalog": source["catalog_sha256"],
            "expected_catalog": baseline["source_catalog"]["sha256"],
        })
    for name in raw_names:
        raw = (run / name).read_bytes()
        item["raw"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    report["actual_results"].append(item)
Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": args.output, "zip": report["actual_zip_sha256"], "runs": [{"run": x["run"], "pid": x["completion"]["pid" if args.layout == "group-v4" else "process_id"], "exit": x["completion"]["exit_code"], "source": x["source"], "stdout_tail": x["stdout_tail"][-1:]} for x in report["actual_results"]]}, ensure_ascii=False))

"""Replay the frozen judge inputs, without executing any product task.

The original Qwen calls exhausted 1200 tokens on reasoning (null content,
finish_reason=length). This diagnostic revision disables thinking, as the
candidate's MemoryProvider already does. Original calls/results stay intact.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import httpx

import eval_v4 as evaluation


def diagnose(item, source, output, settings, helper):
    original = evaluation.read(source / item["execution_id"] / "result.json")
    request = dict(original["judge"]["calls"][0]["request"])
    request["enable_thinking"] = False
    capture = helper.CapturingTransport(settings.llm_timeout)
    result = {"execution_id": item["execution_id"], "source_result_sha256": item["source_result_sha256"],
              "calibrated": False, "hard_gate": False, "same_model_as_agent": True,
              "request": request, "result": {"verdict": "unknown", "findings": []}}
    try:
        with httpx.Client(transport=capture) as client:
            response = client.post(settings.openai_base_url.rstrip("/") + "/chat/completions", json=request,
                                   headers={"Authorization": "Bearer " + settings.openai_api_key})
            response.raise_for_status()
        from app.llm.structured_output import extract_json_object
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Judge returned no visible JSON content")
        verdict = extract_json_object(content)
        if verdict["verdict"] not in ("pass", "fail", "unknown") or not isinstance(verdict["findings"], list):
            raise ValueError("Invalid judge verdict/findings")
        for finding in verdict["findings"]:
            if finding["dimension"] not in ("completeness", "grounding", "clarification", "status") or finding["verdict"] not in ("pass", "fail", "unknown"):
                raise ValueError("Invalid finding dimension/verdict")
            if not isinstance(finding["evidence"], str) or not isinstance(finding["reason"], str):
                raise ValueError("Invalid finding evidence/reason")
        result["result"] = verdict
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
        # External diagnostic failures are unknown, never business successes.
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    result["calls"] = capture.calls
    text = json.dumps(result, ensure_ascii=False, indent=2)
    evaluation.write(output / (item["execution_id"] + ".json"), json.loads(helper.CREDENTIAL_VALUE.sub(r"\1[REDACTED]", text)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    batch = evaluation.read(source / "manifest.json")
    if evaluation.config_identity(batch["tree"]) != batch["config_identity"] or evaluation.environment_identity() != batch["environment_identity"]:
        raise ValueError("Configuration/environment differs from the product batch")
    if args.resume:
        manifest = evaluation.read(output / "manifest.json")
        if manifest["runner_sha256"] != evaluation.digest(__file__) or manifest["source_manifest_sha256"] != evaluation.digest(source / "manifest.json"):
            raise ValueError("Diagnostic source/runner changed")
    else:
        output.mkdir()  # Fresh evidence directory; never replace older calls.
        schedule = []
        for item in batch["schedule"]:
            path = source / item["execution_id"] / "result.json"
            original = evaluation.read(path)
            if not original.get("judge", {}).get("calls"):
                raise ValueError(f"Missing captured judge input: {item['execution_id']}")
            schedule.append({"execution_id": item["execution_id"], "source_result_sha256": evaluation.digest(path)})
        manifest = {"source": str(source), "source_manifest_sha256": evaluation.digest(source / "manifest.json"),
                    "runner_sha256": evaluation.digest(__file__), "tree": batch["tree"],
                    "config_identity": batch["config_identity"], "environment_identity": batch["environment_identity"], "schedule": schedule,
                    "started_utc": datetime.now(timezone.utc).isoformat(), "change": "enable_thinking=false; other captured request fields unchanged",
                    "product_tasks_reexecuted": 0, "calibrated": False, "hard_gate": False}
        evaluation.write(output / "manifest.json", manifest)
    for item in manifest["schedule"]:
        if evaluation.digest(source / item["execution_id"] / "result.json") != item["source_result_sha256"]:
            raise ValueError("Source result changed")
    tree = Path(manifest["tree"])
    if evaluation.config_identity(tree) != manifest["config_identity"] or evaluation.environment_identity() != manifest["environment_identity"]:
        raise ValueError("Model configuration changed")
    os.chdir(tree)
    sys.path[:0] = [str(tree / "backend"), str(tree)]
    from app.core.config import get_settings
    settings = get_settings()
    helper = evaluation.load(tree / "work/ceres-next-agent-experience/04/collect_prompt_sample.py", "diagnostic_capture")
    pending = [item for item in manifest["schedule"] if not (output / (item["execution_id"] + ".json")).exists()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda item: diagnose(item, source, output, settings, helper), pending[:args.limit]))
    results = [evaluation.read(output / (item["execution_id"] + ".json")) for item in manifest["schedule"]
               if (output / (item["execution_id"] + ".json")).exists()]
    summary = {"planned": len(manifest["schedule"]), "completed": len(results),
               "verdicts": {verdict: sum(r["result"]["verdict"] == verdict for r in results) for verdict in ("pass", "fail", "unknown")},
               "errors": sum("error" in r for r in results), "calibrated": False, "hard_gate": False,
               "product_tasks_reexecuted": 0}
    evaluation.write(output / "summary.json", summary)
    print(json.dumps(summary))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

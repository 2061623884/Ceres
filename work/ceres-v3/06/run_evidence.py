"""Run an approved V3-06 pytest command with isolated, preserved evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from time import perf_counter


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
EVIDENCE = ROOT / "work" / "ceres-v3" / "06" / "evidence"
DEFAULT_NODE = "tests/test_v3_policy_consultation.py::test_keke_policy_answer_uses_conditions_instead_of_product_recommendation"


def source_hashes() -> dict[str, object]:
    paths = sorted((BACKEND / "app").rglob("*.py"))
    paths += sorted((BACKEND / "tests").rglob("*.py"))
    paths += [
        Path(__file__).resolve(),
        ROOT / "work" / "ceres-v3" / "06" / "compare-policy-request.py",
        ROOT / "work" / "ceres-v3" / "06" / "implementation-seam.md",
        ROOT / "work" / "ceres-v3" / "06" / "fixes.md",
        ROOT / "work" / "ceres-v3" / "06" / "candidate-v2" / "source.zip",
        ROOT / "work" / "ceres-v3" / "06" / "review-v2" / "review-scope.json",
        ROOT / "work" / "ceres-v3" / "06" / "candidate-v3" / "source.zip",
        ROOT / "work" / "ceres-v3" / "06" / "review-v3" / "review-scope.json",
        ROOT / "work" / "ceres-v3" / "05" / "evidence" / "candidate-v5-20261005T230721Z-y3rsbooc" / "role-sampling" / "role-samples" / "R02.json",
        ROOT / "work" / "ceres-v3" / "05" / "evidence" / "controlled-20261005T213814Z-e9eee78c" / "core-001" / "ceres_controlled_trace.py",
    ]
    manifest: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[relative] = digest
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(bytes.fromhex(digest))
    return {"sha256": aggregate.hexdigest(), "files": manifest}


def package_versions() -> dict[str, str | None]:
    packages = (
        "fastapi", "httpx", "langgraph", "openai", "pydantic",
        "pydantic-settings", "pytest", "sqlalchemy",
    )
    versions: dict[str, str | None] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_name", help="Evidence label, such as red-001")
    parser.add_argument("--comparison", action="store_true", help="run the fixed one-pair policy request replay")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    pytest_args = parsed.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    if parsed.comparison and pytest_args:
        parser.error("--comparison takes no extra arguments")
    if not parsed.comparison and not pytest_args:
        pytest_args = [DEFAULT_NODE]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = EVIDENCE / f"{stamp}-{parsed.run_name}"
    temp_dir = run_dir / "temp"
    basetemp = run_dir / "pytest-tmp"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=False)
    temp_dir.mkdir()

    env = os.environ.copy()
    env.update({
        "TEMP": str(temp_dir),
        "TMP": str(temp_dir),
        "DATABASE_URL": f"sqlite:///{(run_dir / 'runtime.sqlite3').as_posix()}",
        "SOURCE_DATABASE_PATH": str(ROOT / "data" / "sale_guide.db"),
        "PYTHONUTF8": "1",
        "LLM_MODE": "offline",
        "RETRIEVAL_MODE": "lexical",
        "RETRIEVAL_INDEX_DIR": "",
        "CERES_V3_LIVE_EVIDENCE_DIR": "",
        "CERES_V3_ROUTE_EVIDENCE_DIR": "",
        "CERES_V3_INDEPENDENT_EVIDENCE_DIR": "",
        "CERES_LIVE_V2_DEMO": "",
        "CERES_LIVE_MEMORY_ACCEPTANCE": "",
        "MERCURY_LIVE": "0",
    })
    if not parsed.comparison and "ceres_controlled_trace" in pytest_args:
        plugin_dir = ROOT / "work" / "ceres-v3" / "05" / "evidence" / "controlled-20261005T213814Z-e9eee78c" / "core-001"
        inherited_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(plugin_dir), inherited_pythonpath)))
        env["CERES_TRACE_PATH"] = str(run_dir / "trace.jsonl")
    if parsed.comparison:
        env.update({
            "LLM_MODE": "live",
            "LLM_MAX_OUTPUT_TOKENS": "3072",
            "PYTHONPATH": str(BACKEND),
        })
        compare_script = ROOT / "work" / "ceres-v3" / "06" / "compare-policy-request.py"
        argv = [sys.executable, "-X", "utf8", str(compare_script), str(run_dir)]
    else:
        argv = [sys.executable, "-X", "utf8", "-m", "pytest", *pytest_args,
                "-p", "no:cacheprovider", "-W", "error::pytest.PytestUnhandledThreadExceptionWarning",
                "--basetemp", str(basetemp)]
    metadata: dict[str, object] = {
        "run_name": parsed.run_name,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": str(BACKEND),
        "argv": argv,
        "wrapper_argv": sys.argv,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "package_versions": package_versions(),
        "stdout_encoding": "utf-8",
        "stderr_encoding": "utf-8",
        "controlled_environment": {
            key: env[key]
            for key in (
            "TEMP", "TMP", "DATABASE_URL", "SOURCE_DATABASE_PATH",
                "PYTHONUTF8", "PYTHONPATH", "LLM_MODE", "LLM_MAX_OUTPUT_TOKENS",
                "RETRIEVAL_MODE", "RETRIEVAL_INDEX_DIR",
                "CERES_V3_LIVE_EVIDENCE_DIR", "CERES_LIVE_V2_DEMO",
                "CERES_V3_ROUTE_EVIDENCE_DIR", "CERES_V3_INDEPENDENT_EVIDENCE_DIR",
                "CERES_LIVE_MEMORY_ACCEPTANCE", "CERES_TRACE_PATH", "MERCURY_LIVE",
            )
            if key in env
        },
        "source_hashes_before": source_hashes(),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    started = perf_counter()
    with (run_dir / "stdout.raw").open("wb") as stdout, (run_dir / "stderr.raw").open("wb") as stderr:
        result = subprocess.run(argv, cwd=BACKEND, env=env, stdout=stdout, stderr=stderr, check=False)
    metadata["exit_code"] = result.returncode
    metadata["elapsed_seconds"] = perf_counter() - started
    metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["source_hashes_after"] = source_hashes()
    metadata["stdout_sha256"] = hashlib.sha256((run_dir / "stdout.raw").read_bytes()).hexdigest()
    metadata["stderr_sha256"] = hashlib.sha256((run_dir / "stderr.raw").read_bytes()).hexdigest()
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(run_dir)
    print(f"process exit code: {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

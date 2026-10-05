from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres")
BACKEND = REPO / "backend"
TESTS = BACKEND / "tests"
RUN_ROOT = REPO / "work" / "ceres-v3" / "04" / "preflight" / "group4-empty-index-016"
SOURCE_DB = REPO / "data" / "sale_guide.db"
REVIEW_SCOPE = REPO / "work" / "ceres-v3" / "04" / "review-scope.json"

NODES = [
    "tests/test_semantic_phase1_purchase.py",
    "tests/test_purchase_selection.py",
    "tests/test_phase2b_chat_confirmation.py::test_ack_is_read_only_then_chat_confirm_buys_only_current_outstanding_rows_and_replays",
    "tests/test_phase2b_chat_confirmation.py::test_matching_runtime_selection_is_not_given_to_model_or_saved_as_context",
    "tests/test_phase2b_chat_confirmation.py::test_explicit_nonmatching_selection_is_rejected_without_partial_cart_write",
    "tests/test_phase2b_chat_confirmation.py::test_stale_runtime_selection_is_refused_without_using_the_current_plan",
    "tests/test_phase2b_chat_confirmation.py::test_questions_block_a_chat_confirmation",
    "tests/test_phase2b_chat_confirmation.py::test_button_confirmation_then_chat_confirmation_does_not_add_twice",
    "tests/test_phase2b_chat_confirmation.py::test_stale_client_task_version_is_rejected_before_chat_confirmation",
    "tests/test_phase2b_chat_confirmation.py::test_chat_confirmation_keeps_existing_supply_and_budget_guards",
    "tests/test_v2_integrated_demo.py::test_two_run_v2_purchase_history_checkout_and_mercury_journey",
]

DEPENDENCIES = [
    "backend/tests/conftest.py",
    "backend/tests/support/v2_fixture.py",
    "backend/tests/support/semantic_agent.py",
    "backend/tests/support/reactive_semantic.py",
    "backend/tests/support/sse_upstream.py",
    "backend/tests/test_semantic_phase1_purchase.py",
    "backend/tests/test_purchase_selection.py",
    "backend/tests/test_phase2b_chat_confirmation.py",
    "backend/tests/test_v2_integrated_demo.py",
    "backend/app/api/mercury.py",
    "backend/app/core/config.py",
    "backend/app/core/database.py",
    "backend/app/main.py",
    "backend/scripts/seed_runtime.py",
    "Mercury/mercury/agent.py",
    "Mercury/mercury/config.py",
    "Mercury/mercury/db.py",
    "Mercury/mercury/tools.py",
]


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hashes(paths: list[str]) -> dict[str, str | None]:
    return {relative: digest(REPO / relative) for relative in sorted(set(paths))}


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    run_id = sys.argv[1]
    if run_id not in {"run-001", "run-002"}:
        raise ValueError(run_id)
    run_dir = RUN_ROOT / run_id
    basetemp = run_dir / "pytest-tmp"
    temp = run_dir / "os-temp"
    basetemp.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

    review = json.loads(REVIEW_SCOPE.read_text(encoding="utf-8"))
    source_paths = list(dict.fromkeys([*review["paths"], *DEPENDENCIES]))
    before = hashes(source_paths)
    write_json(run_dir / "source-check-before.json", {"paths": before})

    env = os.environ.copy()
    env.update(
        {
            "TEMP": str(temp),
            "TMP": str(temp),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "LLM_MODE": "live",
            "BUSINESS_DATA_MODE": "demo",
            "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
            "OPENAI_API_KEY": "codex-test-only-public",
            "LLM_MODEL": "codex-test-model",
            "MEMORY_MODEL": "",
            "KEV_BASE_URL": "http://127.0.0.1:9",
            "RETRIEVAL_MODE": "hybrid",
            "RETRIEVAL_INDEX_DIR": "",
            "EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1",
            "EMBEDDING_API_KEY": "codex-test-only-public",
            "EMBEDDING_MODEL": "codex-test-embedding",
            "EMBEDDING_REVISION": "diagnostic-fixed",
            "EMBEDDING_DIMENSION": "1024",
            "SOURCE_DATABASE_PATH": str(SOURCE_DB),
            "DATABASE_URL": f"sqlite:///{(run_dir / 'runtime.sqlite3').as_posix()}",
            "MERCURY_DB_PATH": str(run_dir / "mercury.sqlite3"),
        }
    )

    pytest_args = [
        "-q",
        "--showlocals",
        "-p",
        "no:cacheprovider",
        "-W",
        "error::pytest.PytestUnhandledThreadExceptionWarning",
        f"--basetemp={basetemp}",
        *NODES,
    ]
    argv = [sys.executable, "-X", "utf8", "-m", "pytest", *pytest_args]
    write_json(
        run_dir / "environment-and-source.json",
        {
            "run_id": run_id,
            "cwd": str(BACKEND),
            "python_executable": sys.executable,
            "python_version": sys.version,
            "pytest_version": __import__("pytest").__version__,
            "argv": argv,
            "basetemp": str(basetemp),
            "temp": str(temp),
            "controlled_environment": {
                key: ("public dummy literal; value omitted" if key in {"OPENAI_API_KEY", "EMBEDDING_API_KEY"} else env[key])
                for key in [
                    "TEMP", "TMP", "PYTHONDONTWRITEBYTECODE", "PYTHONUTF8", "LLM_MODE",
                    "BUSINESS_DATA_MODE", "OPENAI_BASE_URL", "OPENAI_API_KEY", "LLM_MODEL",
                    "MEMORY_MODEL", "KEV_BASE_URL", "RETRIEVAL_MODE", "RETRIEVAL_INDEX_DIR",
                    "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL",
                    "EMBEDDING_REVISION", "EMBEDDING_DIMENSION", "SOURCE_DATABASE_PATH",
                    "DATABASE_URL", "MERCURY_DB_PATH",
                ]
            },
            "selected_nodes": NODES,
            "scope_paths": source_paths,
            "review_scope_sha256": digest(REVIEW_SCOPE),
            "source_zip_sha256": "f4489083318adbf671a465ae4e0a55124f8bcb32b5b5973b712fd1965b3c6049",
            "test_fixture_boundary": "Semantic proposals and Mercury OpenAI SDK are controlled by test fixtures. No live model call is intended.",
            "retrieval_scope": "Process RETRIEVAL_INDEX_DIR is explicitly empty. ordinary client exercises unindexed direct source reads; indexed_client creates its own per-test paired lexical index. No hybrid/vector/live retrieval claim.",
        },
    )
    command = subprocess.list2cmdline(argv)
    (run_dir / "command.txt").write_text(
        f"Working directory: {BACKEND}\nCommand: {command}\n", encoding="utf-8"
    )

    started = time.time()
    proc = subprocess.run(argv, cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finished = time.time()
    (run_dir / "stdout.txt").write_bytes(proc.stdout)
    (run_dir / "stderr.txt").write_bytes(proc.stderr)

    after = hashes(source_paths)
    write_json(run_dir / "source-check-after.json", {"paths": after})
    stdout_hash = hashlib.sha256(proc.stdout).hexdigest()
    stderr_hash = hashlib.sha256(proc.stderr).hexdigest()
    out_text = proc.stdout.decode("utf-8", errors="replace")
    summary = re.search(r"(\d+ passed(?:, \d+ failed)?(?:, \d+ error)?(?:, \d+ skipped)? in [^\r\n]+)", out_text)
    result = {
        "run_id": run_id,
        "started_unix": started,
        "finished_unix": finished,
        "duration_seconds": round(finished - started, 3),
        "exit_code": proc.returncode,
        "summary": summary.group(1) if summary else None,
        "stdout_sha256": stdout_hash,
        "stderr_sha256": stderr_hash,
        "source_hashes_stable": before == after,
        "source_hash_mismatches": [path for path in source_paths if before[path] != after[path]],
    }
    write_json(run_dir / "result.json", result)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

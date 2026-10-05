from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path


REPO = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres")
BACKEND = REPO / "backend"
TESTS = BACKEND / "tests"
WORK = REPO / "work" / "ceres-v3" / "04" / "preflight" / "diagnostic-013"
OVERLAY = WORK / "baseline-overlay"
SOURCE_DB = REPO / "data" / "sale_guide.db"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    mode, nodeid, run_dir_text, basetemp_text = sys.argv[1:5]
    if mode not in {"current", "baseline"}:
        raise ValueError(mode)
    run_dir = Path(run_dir_text).resolve()
    basetemp = Path(basetemp_text).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    basetemp.mkdir(parents=True, exist_ok=True)

    env = {
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
        "PYTHONUTF8": "1",
    }
    os.environ.update(env)

    search_roots: list[Path]
    if mode == "baseline":
        app_root = OVERLAY / "backend"
        mercury_root = OVERLAY / "Mercury"
        search_roots = [TESTS, app_root, mercury_root]
    else:
        app_root = BACKEND
        mercury_root = REPO / "Mercury"
        search_roots = [TESTS, app_root, mercury_root]
    for path in reversed(search_roots):
        sys.path.insert(0, str(path))

    import app
    import app.core.config as app_config
    import app.core.database as db_module
    import mercury
    import pytest

    settings = app_config.get_settings()
    test_paths = [
        TESTS / "conftest.py",
        TESTS / "test_phase2b_chat_confirmation.py",
        TESTS / "test_v2_integrated_demo.py",
        TESTS / "test_semantic_phase1_purchase.py",
    ]
    source_paths = [
        Path(app_config.__file__),
        Path(app.__file__),
        Path(mercury.__file__),
    ]
    app_guide = app_root / "app" / "api" / "guide.py"
    mercury_agent = mercury_root / "mercury" / "agent.py"
    mercury_llm = mercury_root / "mercury" / "llm.py"
    source_paths.extend([app_guide, mercury_agent, mercury_llm])

    def path_record(path: Path) -> dict[str, object]:
        return {"path": str(path.resolve()), "sha256": sha256(path)}

    bootstrap = {
        "mode": mode,
        "nodeid": nodeid,
        "started_unix": time.time(),
        "python": sys.version,
        "python_executable": sys.executable,
        "pytest_version": pytest.__version__,
        "repo_root_for_tests": str(REPO.resolve()),
        "app_module": path_record(Path(app.__file__)),
        "app_config_module": path_record(Path(app_config.__file__)),
        "mercury_module": path_record(Path(mercury.__file__)),
        "source_modules": [path_record(path) for path in source_paths],
        "settings": {
            "root_dir_constant": str(app_config.ROOT_DIR.resolve()),
            "root_dir_property": str(settings.root_dir.resolve()),
            "llm_mode": settings.llm_mode,
            "business_data_mode": settings.business_data_mode,
            "openai_base_url": settings.openai_base_url,
            "openai_api_key_is_controlled_dummy": settings.openai_api_key == env["OPENAI_API_KEY"],
            "llm_model": settings.llm_model,
            "memory_model_empty": settings.memory_model == "",
            "kev_base_url": settings.kev_base_url,
            "retrieval_mode": settings.retrieval_mode,
            "retrieval_index_dir": settings.retrieval_index_dir,
            "source_database_path_env": env["SOURCE_DATABASE_PATH"],
            "source_db_path_before_fixture": str(settings.source_db_path.resolve()),
            "runtime_db_path_before_fixture": str(settings.runtime_db_path.resolve()),
        },
        "source_database": path_record(SOURCE_DB),
        "test_and_fixture_hashes": [path_record(path) for path in test_paths],
        "dotenv_copied": False,
        "controlled_environment_names": sorted(env),
        "external_provider_policy": {
            "public_dummy_openai_key": True,
            "openai_endpoint_is_loopback_unserved": True,
            "memory_model_empty": True,
            "test_semantic_provider_fixture_expected": True,
            "mercury_model_guard_is_test_owned": nodeid.startswith("test_v2_integrated_demo.py"),
        },
    }
    (run_dir / "bootstrap.json").write_text(
        json.dumps(bootstrap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    class Recorder:
        def __init__(self) -> None:
            self.observation: dict[str, object] = {}

        def pytest_runtest_call(self, item):
            current_settings = app_config.get_settings()
            source_fixture = item.funcargs.get("source_database_path")
            semantic_provider = item.funcargs.get("semantic_provider")
            self.observation.update(
                {
                    "nodeid": item.nodeid,
                    "source_database_fixture": str(Path(source_fixture).resolve()) if source_fixture else None,
                    "source_database_fixture_sha256": sha256(Path(source_fixture)) if source_fixture else None,
                    "test_db_url_fixture": item.funcargs.get("test_db_url"),
                    "active_db_engine_url": str(db_module.engine.url) if db_module.engine else None,
                    "settings_root_dir": str(current_settings.root_dir.resolve()),
                    "settings_source_db_path": str(current_settings.source_db_path.resolve()),
                    "settings_runtime_db_path": str(current_settings.runtime_db_path.resolve()),
                    "settings_retrieval_index_dir": current_settings.retrieval_index_dir,
                    "semantic_provider_fixture_type": (
                        f"{type(semantic_provider).__module__}.{type(semantic_provider).__qualname__}"
                        if semantic_provider is not None else None
                    ),
                }
            )

        def pytest_runtest_makereport(self, item, call):
            if call.when == "call":
                provider = item.funcargs.get("semantic_provider")
                requests = getattr(provider, "requests", None)
                if requests is not None:
                    self.observation["semantic_provider_request_count_after_call"] = len(requests)
                    self.observation["semantic_provider_request_types"] = [
                        type(request).__name__ for request in requests
                    ]

        def pytest_sessionfinish(self, session, exitstatus):
            self.observation["pytest_exit_status"] = int(exitstatus)
            (run_dir / "fixture-observation.json").write_text(
                json.dumps(self.observation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    args = [
        "-q",
        "--showlocals",
        "-p",
        "no:cacheprovider",
        "-W",
        "error::pytest.PytestUnhandledThreadExceptionWarning",
        "--basetemp",
        str(basetemp),
        "--rootdir",
        str(BACKEND),
        f"{TESTS / nodeid.split('::', 1)[0]}::{nodeid.split('::', 1)[1]}",
    ]
    recorder = Recorder()
    exit_code = 2
    try:
        with (run_dir / "stdout.txt").open("w", encoding="utf-8", newline="") as stdout, (
            run_dir / "stderr.txt"
        ).open("w", encoding="utf-8", newline="") as stderr:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = int(pytest.main(args, plugins=[recorder]))
    finally:
        result = {
            "mode": mode,
            "nodeid": nodeid,
            "exit_code": exit_code,
            "finished_unix": time.time(),
            "stdout_sha256": sha256(run_dir / "stdout.txt"),
            "stderr_sha256": sha256(run_dir / "stderr.txt"),
            "bootstrap_sha256": sha256(run_dir / "bootstrap.json"),
            "fixture_observation_sha256": sha256(run_dir / "fixture-observation.json"),
        }
        (run_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

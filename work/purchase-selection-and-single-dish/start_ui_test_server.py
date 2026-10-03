"""Start an isolated Ceres API for the controlled browser test."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
SOURCE_DB = ROOT / "data" / "runtime-langgraph" / "sale_guide.sqlite3"
TEST_DB = WORK / "ui-test.sqlite3"
SOURCE_INDEX = ROOT / "data" / "retrieval_index-langgraph"
TEST_INDEX = WORK / "ui-test-retrieval-index"


def sqlite_uri(path: Path, mode: str | None = None) -> str:
    suffix = f"?mode={mode}" if mode else ""
    return f"file:{path.resolve().as_posix()}{suffix}"


def copy_runtime_database() -> None:
    if not TEST_DB.exists():
        with sqlite3.connect(sqlite_uri(SOURCE_DB, "ro"), uri=True) as source:
            with sqlite3.connect(TEST_DB) as target:
                source.backup(target)


def copy_retrieval_index() -> None:
    if not TEST_INDEX.exists():
        shutil.copytree(SOURCE_INDEX, TEST_INDEX)


copy_runtime_database()
copy_retrieval_index()

# These aliases are read by Ceres Settings before app.main imports the database
# module. Setting them before that import also survives Mercury's override=False
# dotenv load. The LLM settings remain untouched; the provider factory is patched
# below so this sidecar does not call a model.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.resolve().as_posix()}"
os.environ["SOURCE_DATABASE_PATH"] = str(TEST_DB.resolve())
os.environ["RETRIEVAL_INDEX_DIR"] = str(TEST_INDEX.resolve())

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
settings = get_settings()
if settings.runtime_db_path.resolve() != TEST_DB.resolve():
    raise RuntimeError("Ceres runtime database did not resolve to the UI test copy")
if settings.source_db_path.resolve() != TEST_DB.resolve():
    raise RuntimeError("Ceres source/recovery database did not resolve to the UI test copy")
if Path(settings.retrieval_index_dir).resolve() != TEST_INDEX.resolve():
    raise RuntimeError("Ceres retrieval index did not resolve to the UI test copy")

with sqlite3.connect(sqlite_uri(TEST_DB, "ro"), uri=True) as db:
    sku_count = db.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0]
    offer_count = db.execute("SELECT COUNT(*) FROM offers").fetchone()[0]

pointer = json.loads((TEST_INDEX / "current.json").read_text(encoding="utf-8"))
index_version = pointer["index_version"]
manifest = json.loads(
    (TEST_INDEX / index_version / "manifest.json").read_text(encoding="utf-8")
)
if sku_count != 321 or offer_count != 321 or manifest["counts"]["skus"] != 321:
    raise RuntimeError(
        f"Expected the existing 321-SKU snapshot; got {sku_count} SKUs, "
        f"{offer_count} offers, index={manifest['counts']['skus']} SKUs"
    )

from app.main import app  # noqa: E402
import app.core.database as db_module  # noqa: E402
import app.llm.provider as provider_module  # noqa: E402
from support.reactive_semantic import ReactiveSemanticProvider  # noqa: E402

test_engine = db_module.create_db_engine(settings.database_url)
db_module.engine = test_engine
db_module.SessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def override_get_db():
    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[db_module.get_db] = override_get_db
reactive_provider = ReactiveSemanticProvider()
provider_module.get_semantic_provider = lambda: reactive_provider

print(
    json.dumps(
        {
            "event": "isolated_sidecar_ready_to_serve",
            "database": str(TEST_DB.resolve()),
            "source_database": str(TEST_DB.resolve()),
            "index_root": str(TEST_INDEX.resolve()),
            "index_version": index_version,
            "sku_count": sku_count,
            "offer_count": offer_count,
            "provider": "ReactiveSemanticProvider",
            "port": 8013,
        },
        ensure_ascii=False,
    ),
    flush=True,
)

import uvicorn  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=8013, reload=False, workers=1)

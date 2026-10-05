"""Freeze this ticket's actual working source and fixture inputs, excluding secrets."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
args.output_dir.mkdir(parents=True)

paths = []
for directory in ("backend/app", "backend/tests", "Mercury/mercury", "Mercury/tests"):
    paths.extend((root / directory).rglob("*.py"))
for directory in ("frontend/src", "frontend/public", "data/fixtures"):
    paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
paths.extend(root / name for name in (
    "backend/pyproject.toml", "frontend/package.json", "frontend/package-lock.json",
    "frontend/tsconfig.json", "frontend/index.html", "frontend/vite.config.ts",
    "frontend/.figma/make/site.json",
    "scripts/seed_runtime.py", "scripts/import_db.py", "scripts/build_retrieval_index.py",
    "AGENTS.md", "frontend/AGENTS.md", "PROJECT.md", "PROJECT-next.md", "prd.md",
    "GLOSSARY.md", "docs/agents/issue-tracker.md", "docs/plans/ceres-v2-spec.md",
))
products = json.loads((root / "data/fixtures/demo-products.json").read_text(encoding="utf-8"))
paths.extend(root / row["image_path"] for row in products["products"] if row.get("image_path"))

hashes = {}
archive = args.output_dir / "source-inputs.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(set(paths)):
        name = path.relative_to(root).as_posix()
        content = path.read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        bundle.writestr(name, content)
    index = root / "work/ceres-v1/02-vector-retrieval/frozen-index"
    for name in ("current.json", "idx-d3e9873a747cb2d6/manifest.json", "idx-d3e9873a747cb2d6/index.sqlite3"):
        content = (index / name).read_bytes()
        target = "data/retrieval_index-v2-frozen/" + name
        hashes[target] = hashlib.sha256(content).hexdigest()
        bundle.writestr(target, content)

record = {
    "git_head": subprocess.check_output(["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    "source_kind": "actual working tree, including inherited effective dirty source; not a clean Git release",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "archive": str(archive.resolve()),
    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "hash_format": "sha256 of raw bytes",
    "files": hashes,
    "prompts": {name: digest for name, digest in hashes.items() if name.startswith("backend/app/prompts/") or name == "Mercury/mercury/prompt.py"},
    "expected": {"products": 65, "offers": 65, "templates": 111, "dish_templates": 105, "index_documents": 170, "vector_dimension": 1024},
    "index_source": "V1 frozen real vectors idx-d3e9873a747cb2d6; embedding revision unspecified, no new V2 embedding claim",
    "settings": json.loads((root / "work/ceres-v2/09/settings-sanitized.json").read_text(encoding="utf-8")),
    "excluded": [".env", "credentials", "runtime databases", "node_modules", ".venv", "cache", "old source catalog"],
}
(root / "work/ceres-v2/09/source-inputs.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"archive": record["archive"], "sha256": record["archive_sha256"], "files": len(hashes)}, ensure_ascii=False))

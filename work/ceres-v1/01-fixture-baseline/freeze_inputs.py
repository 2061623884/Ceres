"""Record the task-01 source overlay and reproducible fixture inputs."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
base_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
baseline_patch = subprocess.check_output(
    ["git", "diff", "--binary", base_commit, "--", "backend/app", "frontend/src",
     ":!backend/app/api/mercury.py"], cwd=ROOT,
)
(OUT / "runtime-baseline.patch").write_bytes(baseline_patch)
runtime_paths = subprocess.check_output(
    ["git", "ls-files", "backend/app", "backend/pyproject.toml", "scripts",
     "Mercury/mercury", "frontend/package.json", "frontend/package-lock.json",
     "frontend/vite.config.ts", "frontend/tsconfig.json", "frontend/index.html",
     "frontend/.figma/make/site.json", "frontend/src"], cwd=ROOT, text=True,
).splitlines()
runtime_hashes = {}
for relative in runtime_paths:
    if Path(relative).suffix in {".py", ".json", ".toml", ".tsx", ".ts", ".css", ".html"}:
        content = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        runtime_hashes[relative] = hashlib.sha256(content).hexdigest()
fixture_hashes = {}
for source in sorted((ROOT / "data/fixtures").glob("*.json")):
    destination = OUT / "frozen-fixtures" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    fixture_hashes[source.name] = hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
requirements = subprocess.check_output(
    [sys.executable, "-m", "pip", "list", "--format=freeze", "--exclude", "sale-guide-backend", "--exclude", "pip"],
    cwd=ROOT, text=True,
)
(OUT / "requirements-frozen.txt").write_text(requirements, encoding="utf-8", newline="\n")
manifest = {
    "base_commit": base_commit,
    "runtime_baseline_patch_sha256": hashlib.sha256(baseline_patch).hexdigest(),
    "source_hash_format": "SHA-256 of file bytes with CRLF normalized to LF",
    "runtime_source_hashes": runtime_hashes,
    "fixture_hashes": fixture_hashes,
    "python": sys.version,
    "node": subprocess.check_output(["node", "--version"], text=True).strip(),
    "npm": subprocess.check_output(["npm.cmd", "--version"], text=True).strip(),
    "requirements_sha256": hashlib.sha256((OUT / "requirements-frozen.txt").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
    "new_sku": "demo:cn-minute-maid-peach-450ml-bottle",
}
(OUT / "frozen-inputs.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"base_commit": base_commit, "runtime_text_files": len(runtime_hashes), "fixture_files": len(fixture_hashes)}, ensure_ascii=False))

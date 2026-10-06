"""Freeze current source into the isolated integration checkout; no runtime DB copy."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--destination", type=Path, required=True)
args = parser.parse_args()
source, destination = args.source.resolve(), args.destination.resolve()
roots = ["backend/app", "backend/tests", "backend/scripts", "backend/pyproject.toml",
         "frontend", "Mercury", "data/fixtures", "scripts", "evals", "docs/agents",
         "docs/plans/ceres-next-agent-experience-spec.md", "tasks/ceres-next-agent-experience.md",
         "AGENTS.md", "GLOSSARY.md", "PROJECT.md", "PROJECT-next.md", "PROJECT-v3.md",
         "prd.md", ".gitignore", ".gitattributes"]
roots.extend(str(p.relative_to(source)).replace("\\", "/") for p in (source / "tasks").glob("ceres-next-agent-experience-*.md"))
roots.extend("work/ceres-next-discussion/" + name for name in ["expected-agent.mmd", "expected-agent.svg", "expected-agent.png", "expected-agent.html", "ticket-breakdown.md"])
roots.append("work/ceres-next-discussion/ticket-drafts")

def git(*arguments):
    return subprocess.check_output(["git", "-C", str(source), *arguments])

paths = set(git("ls-files", "-z", "--", *roots).decode().strip("\0").split("\0"))
paths.update(git("ls-files", "--others", "--exclude-standard", "-z", "--", *roots).decode().strip("\0").split("\0"))
records, deleted = [], []
for relative in sorted(paths - {""}):
    parts = Path(relative).parts
    if any(part in {"node_modules", "dist", ".venv", "__pycache__", "basetemp", ".pytest_cache", "work"} for part in parts[:-1]) and not relative.startswith("work/ceres-next-discussion/"):
        continue
    if any(part.startswith("pytest-") for part in parts) or Path(relative).suffix in {".db", ".sqlite", ".sqlite3", ".pyc", ".log"} or relative.endswith(("-wal", "-shm")):
        continue
    original, target = source / relative, (destination / relative).resolve()
    if not target.is_relative_to(destination):
        raise ValueError(relative)
    if not original.is_file():
        if target.is_file():
            target.unlink()
        deleted.append(relative)
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, target)
    records.append({"path": relative, "sha256": hashlib.sha256(original.read_bytes()).hexdigest()})
for relative in [".env", "Mercury/.env"]:
    original = source / relative
    if original.is_file():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
manifest = {"original_head": git("rev-parse", "HEAD").decode().strip(), "source": str(source),
            "integration_workspace": str(destination), "files": records, "deleted": deleted,
            "original_dirty": git("status", "--short", "--untracked-files=no").decode()}
for directory in [source, destination]:
    output = directory / "work/ceres-next-agent-experience/00-preparation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-baseline.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
staging = destination / "work/ceres-next-agent-experience/00-preparation/source-pathspec.nul"
staging.write_bytes(b"\0".join(row["path"].encode() for row in records) + b"\0")
print(json.dumps({"copied_source_files": len(records), "inherited_deletions": len(deleted), "private_environment_copied_without_logging": True}))

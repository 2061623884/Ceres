"""Retain exact raw execution bytes in Git-safe JSON records."""

import base64
import hashlib
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parent
retained = root / "retained-raw"
entries = []
for source_root in (root / "evidence", root / "preflight"):
    for folder, names, files in os.walk(source_root):
        names[:] = [n for n in names if n.lower() not in {"temp", "tmp", "index", "__pycache__", "retained-raw"} and "basetemp" not in n.lower() and "pytest-tmp" not in n.lower() and not n.lower().endswith("-temp")]
        for name in sorted(files):
            source = Path(folder) / name
            if source.suffix not in {".txt", ".log", ".raw", ".json", ".jsonl", ".sha256"}:
                continue
            relative = source.relative_to(root)
            raw = source.read_bytes()
            record = {"original_path": relative.as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            try:
                record["utf8_text"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                record["base64_bytes"] = base64.b64encode(raw).decode("ascii")
            destination = retained / (hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16] + ".json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            entries.append({"source": relative.as_posix(), "retained": destination.relative_to(root).as_posix(), "bytes": len(raw), "sha256": record["sha256"]})
manifest = {"purpose": "Exact-byte execution evidence; escaped text preserves CRLF/BOM. No weights, databases, indexes or pytest temporary fixture directories.", "entries": entries}
(root / "retained-raw-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"records": len(entries), "original_bytes": sum(x["bytes"] for x in entries), "manifest": str(root / "retained-raw-manifest.json")}, ensure_ascii=False))

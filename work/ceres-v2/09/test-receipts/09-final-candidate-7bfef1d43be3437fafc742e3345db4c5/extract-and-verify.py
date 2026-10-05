import hashlib, json, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

manifest_path = Path(sys.argv[1])
archive_path = Path(sys.argv[2])
destinations = [Path(sys.argv[3]), Path(sys.argv[4])]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
expected = manifest["files"]
actual_archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual_archive_sha != manifest["archive_sha256"]:
    raise SystemExit("archive SHA256 mismatch; extraction stopped")
results = []
with zipfile.ZipFile(archive_path) as z:
    files = [info for info in z.infolist() if not info.is_dir()]
    if len(files) != len(expected):
        raise SystemExit(f"archive member count mismatch: {len(files)} != {len(expected)}")
    if {i.filename for i in files} != set(expected):
        raise SystemExit("archive paths differ from source manifest; extraction stopped")
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=False)
        for info in files:
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or ".." in posix.parts:
                raise SystemExit(f"unsafe archive member path: {info.filename}")
            target = destination.joinpath(*posix.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
        mismatches = []
        for relative, expected_sha in expected.items():
            data = destination.joinpath(*PurePosixPath(relative).parts).read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != expected_sha:
                mismatches.append({"path": relative, "expected": expected_sha, "actual": actual_sha})
        results.append({
            "clone_root": str(destination.resolve()),
            "backend_app_path": str((destination / "backend" / "app").resolve()),
            "mercury_modules_path": str((destination / "Mercury" / "mercury").resolve()),
            "frontend_path": str((destination / "frontend").resolve()),
            "file_count": len(expected),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches[:10],
        })
print(json.dumps({
    "utc": datetime.now(timezone.utc).isoformat(),
    "archive_sha256": actual_archive_sha,
    "source_files": len(expected),
    "clones": results,
}, ensure_ascii=False, indent=2))

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
    raise SystemExit(f"archive SHA256 mismatch: {actual_archive_sha} != {manifest['archive_sha256']}")
with zipfile.ZipFile(archive_path) as z:
    files = [info for info in z.infolist() if not info.is_dir()]
    if len(files) != len(expected):
        raise SystemExit(f"archive member count mismatch: {len(files)} != {len(expected)}")
    if {i.filename for i in files} != set(expected):
        raise SystemExit("archive paths differ from source manifest")
    clones = []
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=False)
        for info in files:
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit(f"unsafe archive member path: {info.filename}")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
        mismatches = []
        for relative, expected_sha in expected.items():
            target = destination.joinpath(*PurePosixPath(relative).parts)
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != expected_sha:
                mismatches.append({"path": relative, "expected": expected_sha, "actual": actual})
        clones.append({
            "clone_root": str(destination.resolve()),
            "backend_app_path": str((destination / "backend" / "app").resolve()),
            "mercury_module_path": str((destination / "Mercury" / "mercury").resolve()),
            "frontend_path": str((destination / "frontend").resolve()),
            "files_expected": len(expected),
            "files_verified": len(expected) - len(mismatches),
            "mismatches": mismatches,
        })
print(json.dumps({
    "utc": datetime.now(timezone.utc).isoformat(),
    "manifest": str(manifest_path),
    "archive": str(archive_path),
    "archive_sha256_actual": actual_archive_sha,
    "archive_sha256_manifest": manifest["archive_sha256"],
    "archive_sha256_expected_from_root_message": "ad45f3bc916f0f61f71c0e9ceb8ef88cd79beae17624a6a7f3c5118d05cf6dde",
    "archive_hashes_match": actual_archive_sha == manifest["archive_sha256"] == "ad45f3bc916f0f61f71c0e9ceb8ef88cd79beae17624a6a7f3c5118d05cf6dde",
    "manifest_file_count": len(expected),
    "expected": manifest.get("expected"),
    "prompt_hashes": manifest.get("prompts"),
    "clones": clones,
}, ensure_ascii=False, indent=2))

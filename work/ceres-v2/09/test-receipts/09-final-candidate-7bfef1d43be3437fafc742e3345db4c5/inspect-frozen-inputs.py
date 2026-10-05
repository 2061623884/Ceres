import hashlib, json, sys, zipfile
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
manifest = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v2\09\source-inputs.json")
archive = Path(r"C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-release-cb9f7fbc8dfe421e85aaa0b7c5c2e7c7\source-inputs.zip")
data = json.loads(manifest.read_text(encoding="utf-8"))
archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
with zipfile.ZipFile(archive) as z:
    names = [i.filename for i in z.infolist() if not i.is_dir()]
    name_set = set(names)
    file_keys = set(data["files"])
    exact = file_keys == name_set
    prefixes = Counter(name.split("/",1)[0] for name in names)
result = {
 "utc": datetime.now(timezone.utc).isoformat(),
 "manifest": str(manifest),
 "archive": str(archive),
 "archive_sha256_actual": archive_sha,
 "archive_sha256_expected": data["archive_sha256"],
 "archive_sha256_match": archive_sha == data["archive_sha256"],
 "manifest_file_count": len(data["files"]),
 "zip_file_count": len(names),
 "manifest_and_zip_paths_exactly_match": exact,
 "zip_top_level_prefixes": dict(prefixes),
 "first_zip_names": names[:15],
 "manifest_expected": data["expected"],
}
print(json.dumps(result, ensure_ascii=False, indent=2))

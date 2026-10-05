import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
out = []
for arg in sys.argv[1:]:
    label, dbraw = arg.split("=", 1)
    db = Path(dbraw).resolve()
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {}
    for name in names:
        quoted = name.replace('"', '""')
        counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
    out.append({"clone": label, "database": str(db), "tables": counts})
    conn.close()
print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "readonly": True, "clones": out}, ensure_ascii=False, indent=2))

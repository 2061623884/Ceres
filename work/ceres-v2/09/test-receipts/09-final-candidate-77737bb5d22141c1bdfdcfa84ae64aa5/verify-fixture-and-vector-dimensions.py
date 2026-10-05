import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

version = "idx-d3e9873a747cb2d6"
results = []
for clone_name in ("cold-1", "cold-2"):
    clone = Path(sys.argv[1]) / clone_name
    db = Path(sys.argv[2]) / f"{clone_name}-runtime.sqlite3"
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    table_info = {r[0]: [c[1] for c in conn.execute(f'PRAGMA table_info("{r[0]}")')] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    products = conn.execute("SELECT COUNT(*) FROM catalog_products WHERE review_status='approved'").fetchone()[0]
    offers = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    template_total = conn.execute("SELECT COUNT(*) FROM purchase_templates").fetchone()[0]
    template_sources = {}
    if "source" in table_info["purchase_templates"]:
        template_sources = dict(conn.execute("SELECT source, COUNT(*) FROM purchase_templates GROUP BY source ORDER BY source").fetchall())
    conn.close()
    index_root = clone / "data" / "retrieval_index-v2-frozen"
    index_dir = index_root / version
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    idx = sqlite3.connect((index_dir / "index.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)
    idx.execute("PRAGMA query_only=ON")
    emb_rows = idx.execute("SELECT dimension, COUNT(*) FROM embeddings GROUP BY dimension ORDER BY dimension").fetchall()
    idx.close()
    embedding = manifest.get("embedding") or {}
    counts = manifest.get("counts") or {}
    results.append({
        "clone_root": str(clone),
        "runtime_db": str(db),
        "catalog_products_approved": products,
        "offers": offers,
        "purchase_templates": template_total,
        "purchase_template_sources": template_sources,
        "frozen_index_dir": str(index_dir),
        "index_version": version,
        "manifest_counts": counts,
        "manifest_embedding_dimension": embedding.get("dimension"),
        "stored_vector_dimension_counts": {str(r[0]): r[1] for r in emb_rows},
    })
print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "read_only": True, "results": results}, ensure_ascii=False, indent=2))

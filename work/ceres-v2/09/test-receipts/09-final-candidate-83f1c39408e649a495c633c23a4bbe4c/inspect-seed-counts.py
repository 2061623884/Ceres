import json, sqlite3, sys
from pathlib import Path
out=[]
for p in map(Path,sys.argv[1:]):
    uri=p.resolve().as_uri()+'?mode=ro'
    c=sqlite3.connect(uri,uri=True)
    c.execute('PRAGMA query_only=ON')
    tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    report={'db':str(p),'tables':tables}
    for table in ('catalog_products','offers','purchase_templates'):
        if table in tables:
            report[table]={'count':c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],'columns':[r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]}
    if 'purchase_templates' in tables:
        for col in ('source_group','source_id','template_type'):
            if col in report['purchase_templates']['columns']:
                report['purchase_templates'][col+'_counts']=[list(r) for r in c.execute(f'SELECT "{col}",COUNT(*) FROM purchase_templates GROUP BY "{col}" ORDER BY "col"')]
    c.close(); out.append(report)
print(json.dumps(out,ensure_ascii=False,indent=2))

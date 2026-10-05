from __future__ import annotations
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

root=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9')
started=datetime.now(timezone.utc).isoformat()
report={'started_utc':started,'finished_utc':None,'executable':sys.executable,'argv':sys.orig_argv,'cwd':str(Path.cwd()),'sqlite':'mode=ro; PRAGMA query_only=ON','databases':[]}
for label in ('owner-71','owner-72'):
    db=root/label/'ceres-ui.sqlite3'
    c=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True); c.execute('PRAGMA query_only=ON')
    owners=[{'owner_id':r[0],'created_at':r[1]} for r in c.execute('SELECT id,created_at FROM owners ORDER BY created_at')]
    carts=[]
    for r in c.execute('SELECT c.owner_id,c.store_id,c.version,ci.sku_id,ci.quantity,ci.unit_price_fen FROM carts c LEFT JOIN cart_items ci ON ci.cart_id=c.id ORDER BY c.owner_id,ci.sku_id'):
        carts.append({'owner_id':r[0],'store_id':r[1],'version':r[2],'sku_id':r[3],'quantity':r[4],'unit_price_fen':r[5]})
    orders=[]
    for r in c.execute('SELECT o.order_id,o.user_id,o.status,o.total_fen,oi.sku_id,oi.product_name,oi.quantity,oi.unit_price_fen FROM orders o LEFT JOIN order_items oi ON oi.order_id=o.order_id ORDER BY o.created_at,oi.item_id'):
        orders.append({'order_id':r[0],'owner_id':r[1],'status':r[2],'total_fen':r[3],'sku_id':r[4],'product_name':r[5],'quantity':r[6],'unit_price_fen':r[7]})
    sessions=[{'session_id':r[0],'owner_id':r[1],'selected_order_id':r[2]} for r in c.execute('SELECT session_id,owner_id,selected_order_id FROM mercury_sessions ORDER BY created_at')]
    trace={r[0]:r[1] for r in c.execute('SELECT phase,COUNT(*) FROM trace_events GROUP BY phase')}
    receipt={'label':label,'db_path':str(db),'owners':owners,'carts':carts,'orders':orders,'mercury_sessions':sessions,'trace_phase_counts':trace}
    c.close(); report['databases'].append(receipt)
report['finished_utc']=datetime.now(timezone.utc).isoformat()
out=root/'ui-two-db-readonly-audit.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

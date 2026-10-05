from __future__ import annotations
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

root=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9')
run=Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826')
results=json.loads((run/'ui-results.json').read_text(encoding='utf-8'))
labels=('owner-71','owner-72')
report={'started_utc':datetime.now(timezone.utc).isoformat(),'executable':sys.executable,'argv':sys.orig_argv,'cwd':str(Path.cwd()),'access':'SQLite URI mode=ro; PRAGMA query_only=ON','runs':[]}
for label,result in zip(labels,results):
    db=root/label/'ceres-ui.sqlite3'
    con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
    con.execute('PRAGMA query_only=ON')
    owner=result['owner_id']; order_id=result['checkout']['order']['order_id']
    order=con.execute('SELECT order_id,user_id,status,total_fen,created_at FROM orders WHERE order_id=?',(order_id,)).fetchone()
    items=[{'sku_id':r[0],'product_name':r[1],'quantity':r[2],'unit_price_fen':r[3]} for r in con.execute('SELECT sku_id,product_name,quantity,unit_price_fen FROM order_items WHERE order_id=? ORDER BY item_id',(order_id,))]
    cart=[{'version':r[0],'sku_id':r[1],'quantity':r[2],'unit_price_fen':r[3]} for r in con.execute('SELECT c.version,ci.sku_id,ci.quantity,ci.unit_price_fen FROM carts c LEFT JOIN cart_items ci ON ci.cart_id=c.id WHERE c.owner_id=? ORDER BY ci.sku_id',(owner,))]
    sessions=[{'session_id':r[0],'selected_order_id':r[1]} for r in con.execute('SELECT session_id,selected_order_id FROM mercury_sessions WHERE owner_id=? ORDER BY created_at',(owner,))]
    trace_columns=[r[1] for r in con.execute('PRAGMA table_info(trace_events)')]
    phases={r[0]:r[1] for r in con.execute('SELECT phase,COUNT(*) FROM trace_events GROUP BY phase')}
    trace={'columns':trace_columns,'phase_counts_all_db':phases,'model_call_started_all_db':con.execute("SELECT COUNT(*) FROM trace_events WHERE phase='model_call_started'").fetchone()[0]}
    session_ids=[s['session_id'] for s in sessions]
    if 'session_id' in trace_columns and session_ids:
        marks=','.join('?' for _ in session_ids)
        trace['selected_owner_session_phase_counts']={r[0]:r[1] for r in con.execute(f'SELECT phase,COUNT(*) FROM trace_events WHERE session_id IN ({marks}) GROUP BY phase',session_ids)}
    report['runs'].append({'run':result['url'],'owner_id':owner,'order_id_expected_from_ui':order_id,'order_row':None if order is None else {'order_id':order[0],'owner_id':order[1],'status':order[2],'total_fen':order[3],'created_at':order[4]},'order_items':items,'cart_rows':cart,'mercury_sessions':sessions,'trace_evidence':trace,'ui_turn_requests':[r for r in result['requests'] if '/turns/' in r['url']],'page_errors':result['page_errors']})
    con.close()
report['finished_utc']=datetime.now(timezone.utc).isoformat()
out=run/'ui-databases-readonly.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

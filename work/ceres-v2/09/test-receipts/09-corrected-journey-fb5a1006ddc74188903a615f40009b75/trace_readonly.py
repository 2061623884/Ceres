from __future__ import annotations
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\09-corrected-journey-fb5a1006ddc74188903a615f40009b75')
db = root / 'pytest-temp' / 'live-journey-corrected' / 'test_live_v2_purchase_history_1' / 'test.sqlite3'
out = root / 'corrected-run2-read-history-trace-readonly.txt'
request_id = 'c825eac3-7164-4f82-82db-731844bb2dc4'
start = datetime.now(timezone.utc).isoformat()
lines = [
 'Ceres corrected journey run 2 read-only trace inspection',
 f'start_utc={start}',
 f'python_executable={sys.executable}',
 f'argv={json.dumps(sys.orig_argv, ensure_ascii=False)}',
 f'cwd={Path.cwd()}',
 f'database={db}',
 'sqlite_mode=ro; PRAGMA query_only=ON',
 f'request_id={request_id}',
]
status = 0
try:
    uri = db.resolve().as_uri() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.execute('PRAGMA query_only=ON')
    msg = con.execute('SELECT role,kind,content,status,created_at FROM guide_messages WHERE request_id=? ORDER BY sequence', (request_id,)).fetchall()
    lines.append(f'guide_message_rows={len(msg)}')
    for role, kind, content, state, created in msg:
        lines.append('guide_message=' + json.dumps({'role':role,'kind':kind,'content':content,'status':state,'created_at':created}, ensure_ascii=False))
    rows = con.execute('SELECT event_id,trace_id,phase,model_mode,input_summary,output_summary,error,duration_ms,created_at FROM trace_events WHERE request_id=? ORDER BY created_at,event_id', (request_id,)).fetchall()
    lines.append(f'trace_event_rows={len(rows)}')
    for event_id, trace_id, phase, mode, input_summary, output_summary, error, duration, created in rows:
        summary = None
        raw = output_summary if output_summary is not None else input_summary
        if raw:
            try: summary = json.loads(raw)
            except json.JSONDecodeError: summary = raw
        if isinstance(summary, dict):
            summary = {k: summary[k] for k in ('call_number','stage','repair','read_result_count','status','duration_ms','plan_effect','actions','model') if k in summary}
        lines.append('trace=' + json.dumps({'event_id':event_id,'trace_id':trace_id,'phase':phase,'model_mode':mode,'summary':summary,'error':error,'duration_ms':duration,'created_at':created}, ensure_ascii=False))
    con.close()
except Exception as exc:
    status = 1
    lines.append(f'diagnostic_error={type(exc).__name__}: {exc}')
lines.extend([f'finish_utc={datetime.now(timezone.utc).isoformat()}', f'diagnostic_exit_code={status}'])
report = '\n'.join(lines) + '\n'
out.write_text(report, encoding='utf-8')
sys.stdout.write(report)
raise SystemExit(status)

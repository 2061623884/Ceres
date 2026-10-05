import json, re, sqlite3, sys
from pathlib import Path
from datetime import datetime, timezone

def parse_dotenv(path):
    vals={}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$',line)
        if m:
            v=m.group(2).strip()
            if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'":v=v[1:-1]
            vals[m.group(1)]=v
    return vals

def redact(s,secrets):
    if s is None:return None
    for x in secrets:
        if len(x)>=6:s=s.replace(x,'<REDACTED>')
    s=re.sub(r'(?i)(authorization\s*[:=]\s*[\"\']?bearer\s+)[^\s\"\']+','\\1<REDACTED>',s)
    s=re.sub(r'(?i)(api[_ -]?key\s*[:=]\s*)[^\s,}\]]+','\\1<REDACTED>',s)
    s=re.sub(r'https?://[^\s\"\']+','<URL_REDACTED>',s)
    return s
allow={'model','provider','provider_request_id','call_id','finish_reason','finish','usage','prompt_tokens','completion_tokens','total_tokens','input_tokens','output_tokens','elapsed_ms','latency_ms','duration_ms','status','ok','attempt','retry_count','request_id','answer_status','output_chars','response_chars','message_chars','call_count','trace_id','phase','error_code','error_type','error'}
def safe_fields(v):
    if isinstance(v,dict):
        out={}
        for k,val in v.items():
            if k.lower() in allow:
                out[k]=safe_fields(val) if isinstance(val,(dict,list)) else (val[:500] if isinstance(val,str) else val)
            elif isinstance(val,(dict,list)):
                nested=safe_fields(val)
                if nested:out[k]=nested
        return out
    if isinstance(v,list):return [safe_fields(x) for x in v]
    return v
root=Path(sys.argv[1]); run=Path(sys.argv[2]); dotenv=parse_dotenv(root/'Ceres'/'work'/'ceres-v2'/'09'/'source-inputs.json') if False else parse_dotenv(run/'cold-1'/'.env')
items=[('stable-1',run/'pytest-temp'/'live-memory'/'test_real_reply_and_background0'/'test.sqlite3','live-memory-stable-1'),('explicit-conflict-2',run/'pytest-temp'/'live-memory'/'test_real_reply_and_background5'/'test.sqlite3','live-memory-explicit-conflict-2')]
out=[]
for label,dbpath,rid in items:
    uri=dbpath.resolve().as_uri()+'?mode=ro'; c=sqlite3.connect(uri,uri=True); c.execute('PRAGMA query_only=ON')
    cols=[r[1] for r in c.execute('PRAGMA table_info(trace_events)')]
    rows=c.execute('SELECT event_id,trace_id,request_id,session_id,task_id,owner_id,phase,model_mode,workflow_version,input_summary,output_summary,error,duration_ms,created_at FROM trace_events WHERE request_id=? ORDER BY created_at,event_id',(rid,)).fetchall()
    events=[]
    for row in rows:
        d=dict(zip(['event_id','trace_id','request_id','session_id','task_id','owner_id','phase','model_mode','workflow_version','input_summary','output_summary','error','duration_ms','created_at'],row))
        parsed={}
        for field in ('input_summary','output_summary'):
            val=d[field]
            if val:
                try:
                    obj=json.loads(val)
                    parsed[field]={'keys':sorted(obj.keys()) if isinstance(obj,dict) else [],'safe':safe_fields(obj)}
                except (json.JSONDecodeError,TypeError):
                    parsed[field]={'notJson':True,'chars':len(val),'sha256':__import__('hashlib').sha256(val.encode()).hexdigest()}
        events.append({'event_id':d['event_id'],'trace_id':d['trace_id'],'request_id':d['request_id'],'session_id':d['session_id'],'task_id':d['task_id'],'owner_id':d['owner_id'],'phase':d['phase'],'model_mode':d['model_mode'],'workflow_version':d['workflow_version'],'duration_ms':d['duration_ms'],'created_at':d['created_at'],'summaries':parsed,'error':redact(d['error'],[v for k,v in dotenv.items() if k.endswith('_KEY') or k.endswith('_TOKEN') or k.endswith('_SECRET')])})
    c.close()
    out.append({'label':label,'database':str(dbpath),'readonly':True,'query_only':True,'tableColumns':cols,'eventCount':len(events),'phases':[e['phase'] for e in events],'events':events})
path=run/'live-trace-readonly.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))

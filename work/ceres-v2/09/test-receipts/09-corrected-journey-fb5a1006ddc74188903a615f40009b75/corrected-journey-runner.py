import json, os, queue, re, subprocess, sys, threading
from datetime import datetime, timezone
from pathlib import Path

def utc(): return datetime.now(timezone.utc).isoformat()
def console_emit(text,kind):
    if kind!='stdout':
        sys.stdout.write(text); sys.stdout.flush(); return
    try: obj=json.loads(text.strip())
    except Exception:
        sys.stdout.write(text); sys.stdout.flush(); return
    if not isinstance(obj,dict):
        sys.stdout.write(text); sys.stdout.flush(); return
    view={}
    for key in ('run','mode','llm_model','memory_model','retrieval_mode','index_version','embedding_model','turn','action','input','elapsed_ms','reply','versions','actions'):
        if key in obj:view[key]=obj[key]
    if obj.get('turn','').endswith('_raw'):
        view={'run':obj.get('run'),'turn':obj.get('turn'),'elapsed_ms':obj.get('elapsed_ms'),'note':'full raw payload retained in external stdout file'}
    if 'order' in obj:
        order=obj['order'];view['order']={k:order.get(k) for k in ('order_id','status','total_fen','items') if k in order}
    if 'orders' in obj:
        view['orders']=[{k:o.get(k) for k in ('order_id','status','total_fen') if k in o} for o in obj['orders']]
    if 'result' in obj and obj.get('turn'):
        r=obj['result'];view['result']={k:r.get(k) for k in ('status','answer_status','purchase_step','message') if k in r}
        if isinstance(r.get('plan'),dict):view['result']['plan']={k:r['plan'].get(k) for k in ('plan_id','plan_version','selected_total_fen','targets','items') if k in r['plan']}
    sys.stdout.write(json.dumps(view,ensure_ascii=False)+'\n');sys.stdout.flush()
def parse_dotenv(path):
    values={}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$',line)
        if m:
            value=m.group(2).strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
            values[m.group(1)]=value
    return values
def sanitize(text,secrets):
    for secret in secrets:
        if len(secret)>=6: text=text.replace(secret,'<REDACTED>')
    text=re.sub(r'(?i)(authorization\s*[:=]\s*[\"\']?bearer\s+)[^\s\"\']+','\\1<REDACTED>',text)
    text=re.sub(r'("base_url"\s*:\s*")[^"]*(")',r'\1<REDACTED>\2',text)
    return text
cfg=json.load(open(sys.argv[1],encoding='utf-8-sig'))
py=cfg['python']; cwd=Path(cfg['cwd']); clone=Path(cfg['clone']); run=Path(sys.argv[2]); env=os.environ.copy()
dotenv=parse_dotenv(Path(cfg['dotenv']))
for key in dotenv: env.pop(key,None)
for key in list(env):
    if key.startswith('LLM_') or key.startswith('MEMORY_') or key.startswith('OPENAI_') or key.startswith('EMBEDDING_') or key.startswith('RETRIEVAL_') or key in {'BUSINESS_DATA_MODE','SOURCE_DATABASE_PATH','DATABASE_URL','MERCURY_DB_PATH','INTERNAL_ADMIN_TOKEN','CERES_LIVE_MEMORY_ACCEPTANCE','CERES_LIVE_V2_DEMO','PYTEST_ADDOPTS'}:
        env.pop(key,None)
env.update(cfg['env_overrides'])
args=['-X','utf8','-u','-m','pytest','-s','-q','-p','no:cacheprovider','-W','error::pytest.PytestUnhandledThreadExceptionWarning','--basetemp',cfg['pytest_basetemp'],cfg['test_path']]
cmd=[py,*args]
raw_out=run/'live-memory.stdout.raw.txt'; raw_err=run/'live-memory.stderr.raw.txt'; safe_out=run/'live-memory.stdout.safe.txt'; safe_err=run/'live-memory.stderr.safe.txt'; recpath=run/'live-memory.command.json'; q=queue.Queue(); sentinels=0
start=utc()
with raw_out.open('wb') as out_file, raw_err.open('wb') as err_file, safe_out.open('w',encoding='utf-8',newline='') as safe_out_file, safe_err.open('w',encoding='utf-8',newline='') as safe_err_file:
    proc=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    def pump(stream,kind,raw,safe):
        with raw,safe:
            while True:
                chunk=stream.readline()
                if not chunk: break
                raw.write(chunk); raw.flush()
                q.put((kind,chunk))
        q.put((kind,None))
    threads=[threading.Thread(target=pump,args=(proc.stdout,'stdout',out_file,safe_out_file),daemon=True),threading.Thread(target=pump,args=(proc.stderr,'stderr',err_file,safe_err_file),daemon=True)]
    for t in threads:t.start()
    while sentinels<2:
        kind,chunk=q.get()
        if chunk is None:
            sentinels+=1; continue
        text=chunk.decode('utf-8',errors='replace')
        cleaned=sanitize(text,[dotenv.get(k,'') for k in dotenv if k.endswith('_KEY') or k.endswith('_TOKEN') or k.endswith('_SECRET')])
        if kind=='stdout': safe_out_file.write(cleaned); safe_out_file.flush()
        else: safe_err_file.write(cleaned); safe_err_file.flush()
        console_emit(cleaned,kind)
    for t in threads:t.join()
    returncode=proc.wait()
end=utc()
record={'suite':cfg['suite'],'startUtc':start,'endUtc':end,'executable':py,'argv':args,'cwd':str(cwd),'env_overrides':cfg['env_overrides'],'dotenv_key_names_removed_from_process':sorted(dotenv.keys()),'model_fields_not_overridden':['LLM_MODE','LLM_MODEL','MEMORY_MODEL','OPENAI_BASE_URL','OPENAI_API_KEY','EMBEDDING_MODEL','EMBEDDING_BASE_URL','EMBEDDING_API_KEY'],'pytest_exit':returncode,'runner_exit':0,'raw_stdout':str(raw_out),'raw_stderr':str(raw_err),'safe_stdout':str(safe_out),'safe_stderr':str(safe_err),'credentials_present_in_clone_dotenv':{k:bool(v) for k,v in dotenv.items() if k.endswith('_KEY') or k.endswith('_TOKEN') or k.endswith('_SECRET')}}
recpath.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8'); (run/'live-memory.pytest-exit.txt').write_text(str(returncode),encoding='ascii'); print(json.dumps({'suite':cfg['suite'],'pytest_exit':returncode,'command_record':str(recpath),'raw_stdout':str(raw_out),'raw_stderr':str(raw_err)},ensure_ascii=False),flush=True); sys.exit(returncode)


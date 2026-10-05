from __future__ import annotations
import json, os, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

base = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9')
clone = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\09-corrected-journey-fb5a1006ddc74188903a615f40009b75\cold-journey')
python = Path(r'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\backend\.venv\Scripts\python.exe')
seed = clone / 'scripts' / 'seed_runtime.py'
report=[]
for host_octet in (71,72):
    d=base/f'owner-{host_octet}'
    database=d/'ceres-ui.sqlite3'
    mercury=d/'mercury-ui.sqlite3'
    source=d/'source-not-imported.db'
    env=os.environ.copy()
    env.update({
        'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1',
        'DATABASE_URL':'sqlite:///'+database.as_posix(),
        'MERCURY_DB_PATH':str(mercury),
        'SOURCE_DATABASE_PATH':str(source),
        'LLM_MODE':'offline','LLM_MODEL':'','MEMORY_MODEL':'',
        'OPENAI_BASE_URL':'','OPENAI_API_KEY':'',
        'RETRIEVAL_INDEX_DIR':'','BUSINESS_DATA_MODE':'demo',
    })
    argv=[str(python),'-X','utf8','-u',str(seed),'--fixture-only']
    started=datetime.now(timezone.utc).isoformat()
    proc=subprocess.run(argv,cwd=str(clone),env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    ended=datetime.now(timezone.utc).isoformat()
    (d/'seed.stdout.raw.txt').write_text(proc.stdout,encoding='utf-8')
    (d/'seed.stderr.raw.txt').write_text(proc.stderr,encoding='utf-8')
    receipt={
        'started_utc':started,'finished_utc':ended,'argv':argv,'cwd':str(clone),
        'python_version':subprocess.run([str(python),'--version'],capture_output=True,text=True).stdout.strip(),
        'environment':{k:env[k] for k in ('PYTHONUTF8','PYTHONDONTWRITEBYTECODE','DATABASE_URL','MERCURY_DB_PATH','SOURCE_DATABASE_PATH','LLM_MODE','LLM_MODEL','MEMORY_MODEL','OPENAI_BASE_URL','OPENAI_API_KEY','RETRIEVAL_INDEX_DIR','BUSINESS_DATA_MODE')},
        'exit_code':proc.returncode,'stdout_file':str(d/'seed.stdout.raw.txt'),'stderr_file':str(d/'seed.stderr.raw.txt'),
    }
    if proc.returncode==0:
        con=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True); con.execute('PRAGMA query_only=ON')
        receipt['counts']={table:con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in ('catalog_products','offers','purchase_templates','owners','orders','cart_items')}
        con.close()
        receipt['source_fixture_exists']=False
        receipt['source_path_exists']=source.exists()
    (d/'seed.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    report.append(receipt)
print(json.dumps(report,ensure_ascii=False,indent=2))
if any(r['exit_code'] for r in report): raise SystemExit(1)

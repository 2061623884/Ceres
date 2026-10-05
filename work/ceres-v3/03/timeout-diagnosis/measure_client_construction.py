import datetime, httpx, json, pathlib, statistics, sys, time
root=pathlib.Path(__file__).resolve().parents[4]
out=pathlib.Path(__file__).resolve().parent
samples=[]
for index in range(1,4):
    t0=time.perf_counter()
    client=httpx.Client(timeout=3.0)
    construct=(time.perf_counter()-t0)*1000
    t1=time.perf_counter()
    client.close()
    close=(time.perf_counter()-t1)*1000
    samples.append({'index':index,'construct_ms':round(construct,3),'close_ms':round(close,3)})
record={'event':'httpx_client_local_construction_only_no_network','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':sys.executable,'cwd':str(pathlib.Path.cwd()),'httpx_version':httpx.__version__,'timeout_seconds':3.0,'trust_env':True,'network_calls':0,'samples':samples,'construct_median_ms':round(statistics.median(s['construct_ms'] for s in samples),3)}
(out/'httpx-client-construction-only.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,indent=2))

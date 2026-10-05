from __future__ import annotations
import ast, datetime, hashlib, json, os, pathlib, sys, time

root = pathlib.Path(__file__).resolve().parents[4]
evidence = pathlib.Path(__file__).resolve().parent
source_path = root / 'backend/app/llm/kev_provider.py'
source_bytes = source_path.read_bytes()
source_hash = hashlib.sha256(source_bytes).hexdigest()
source = source_bytes.decode('utf-8')
tree = ast.parse(source, filename=str(source_path))
names = {'INSTRUCTIONS','CRITERIA','CRITERIA_VERSION','KEV_TIMEOUT_SECONDS'}
constants = {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                constants[target.id] = ast.literal_eval(node.value)
if constants.keys() != names:
    raise RuntimeError(f'Could not read provider constants: {sorted(constants)}')
sys.path.insert(0, str(root / 'backend'))
import httpx
from app.llm.kev_provider import KevResponse, INSTRUCTIONS, CRITERIA, CRITERIA_VERSION, KEV_TIMEOUT_SECONDS
if (INSTRUCTIONS, CRITERIA, CRITERIA_VERSION, KEV_TIMEOUT_SECONDS) != (constants['INSTRUCTIONS'],constants['CRITERIA'],constants['CRITERIA_VERSION'],constants['KEV_TIMEOUT_SECONDS']):
    raise RuntimeError('Imported constants do not match source AST')
if KEV_TIMEOUT_SECONDS != 3.0:
    raise RuntimeError(f'Expected 3.0s timeout, got {KEV_TIMEOUT_SECONDS!r}')
base_url = os.environ.get('KEV_BASE_URL', 'http://127.0.0.1:18009').rstrip('/')
if base_url != 'http://127.0.0.1:18009':
    raise RuntimeError(f'Unexpected endpoint {base_url!r}')
state = {'current_role':'可可导购','selected_object':None,'recent_dialogue':[],'utterance':'你好'}
payload = {'state':state,'model':'kev-latest','questions':{'service':{'type':'choice','instructions':constants['INSTRUCTIONS'],'criteria':constants['CRITERIA']}}}
payload_bytes = json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
(evidence/'diagnostic-request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
record = {
 'event':'single_diagnostic_httpx_stage_timing_not_quality_case',
 'criteria_version':CRITERIA_VERSION,
 'source_path':str(source_path),
 'source_sha256':source_hash,
 'request_sha256_compact_utf8':hashlib.sha256(payload_bytes).hexdigest(),
 'state':state,
 'endpoint':base_url+'/v1/systemone',
 'timeout_seconds':KEV_TIMEOUT_SECONDS,
 'runtime':{'python':sys.executable,'python_version':sys.version.replace('\n',' '),'cwd':str(pathlib.Path.cwd()),'httpx_version':httpx.__version__,'client_trust_env':True,'KEV_BASE_URL':base_url,'proxy_values_not_recorded':True},
 'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
client_started=time.perf_counter()
client=httpx.Client(timeout=KEV_TIMEOUT_SECONDS)
record['client_construct_ms']=round((time.perf_counter()-client_started)*1000,3)
request_started=time.perf_counter()
try:
    response=client.post(base_url+'/v1/systemone',json=payload)
    record['http_post_roundtrip_ms']=round((time.perf_counter()-request_started)*1000,3)
    record['http_status']=response.status_code
    record['response_elapsed_seconds']=response.elapsed.total_seconds()
    record['safe_response_headers']={k:v for k,v in response.headers.items() if k.lower() in {'date','server','content-length','content-type','server-timing','x-typesafe-request-id'}}
    response.raise_for_status()
    parse_started=time.perf_counter()
    raw=response.json()
    record['json_parse_ms']=round((time.perf_counter()-parse_started)*1000,3)
    validate_started=time.perf_counter()
    parsed=KevResponse.model_validate(raw)
    record['pydantic_validation_ms']=round((time.perf_counter()-validate_started)*1000,3)
    record['raw_response']=raw
    record['validated_choice']=parsed.answers.service.model_dump(mode='json')
    record['service_latency_ms']=raw.get('latency_ms')
    record['status']='response_received_and_parsed'
except Exception as exc:
    record['http_post_roundtrip_ms']=round((time.perf_counter()-request_started)*1000,3)
    record['status']='failed'
    record['error_type']=type(exc).__name__
    record['error']=str(exc)
    if 'response' in locals():
        record['http_status']=response.status_code
        record['raw_body_text']=response.text
finally:
    close_started=time.perf_counter()
    client.close()
    record['client_close_ms']=round((time.perf_counter()-close_started)*1000,3)
record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
record['source_sha256_after']=hashlib.sha256(source_path.read_bytes()).hexdigest()
record['source_unchanged_during_run']=record['source_sha256']==record['source_sha256_after']
(evidence/'diagnostic-timing.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:record.get(k) for k in ('status','started_utc','finished_utc','client_construct_ms','http_post_roundtrip_ms','json_parse_ms','pydantic_validation_ms','client_close_ms','http_status','service_latency_ms','safe_response_headers','validated_choice','error_type','error','source_unchanged_during_run')},ensure_ascii=False))
if record['status']!='response_received_and_parsed' or not record['source_unchanged_during_run']:
    raise SystemExit(1)

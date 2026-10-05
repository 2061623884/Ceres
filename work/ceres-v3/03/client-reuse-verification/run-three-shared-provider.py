from __future__ import annotations
import ast, datetime, hashlib, json, pathlib, sys, time

root=pathlib.Path(__file__).resolve().parents[4]
evidence=pathlib.Path(__file__).resolve().parent
provider_path=root/'backend/app/llm/kev_provider.py'
chat_path=root/'backend/app/api/chat.py'
main_path=root/'backend/app/main.py'
cases_path=root/'work/ceres-v3-discussion/kev-local-probe/chinese-pilot.json'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
source_bytes=provider_path.read_bytes()
source_hash=hashlib.sha256(source_bytes).hexdigest()
tree=ast.parse(source_bytes.decode('utf-8'),filename=str(provider_path))
names={'INSTRUCTIONS','CRITERIA','CRITERIA_VERSION','KEV_TIMEOUT_SECONDS'}
constants={}
for node in tree.body:
    if isinstance(node,ast.Assign):
        for target in node.targets:
            if isinstance(target,ast.Name) and target.id in names:
                constants[target.id]=ast.literal_eval(node.value)
if constants.keys()!=names:
    raise RuntimeError(f'Could not freeze constants from new provider: {sorted(constants)}')
source_files={str(p.relative_to(root)):sha(p) for p in (provider_path,chat_path,main_path)}
cases_bytes=cases_path.read_bytes()
cases_hash=hashlib.sha256(cases_bytes).hexdigest()
all_cases=json.loads(cases_bytes.decode('utf-8'))
target_ids=['momo-new-shopping','cancel-without-object','cancel-shopping-list']
cases=[next(c for c in all_cases if c['id']==case_id) for case_id in target_ids]
if [c['id'] for c in cases]!=target_ids:
    raise RuntimeError('Original cases missing or reordered')
requests=[]
for case in cases:
    payload={'state':case['state'],'model':'kev-latest','questions':{'service':{'type':'choice','instructions':constants['INSTRUCTIONS'],'criteria':constants['CRITERIA']}}}
    payload_bytes=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    requests.append({'case_id':case['id'],'expected_unchanged':case['expected'],'payload':payload,'payload_sha256_compact_utf8':hashlib.sha256(payload_bytes).hexdigest()})
(evidence/'frozen-requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

sys.path.insert(0,str(root/'backend'))
from app.core.config import get_settings
from app.llm.kev_provider import CRITERIA,CRITERIA_VERSION,INSTRUCTIONS,KEV_TIMEOUT_SECONDS,KevUnavailable,get_kev_provider
if (INSTRUCTIONS,CRITERIA,CRITERIA_VERSION,KEV_TIMEOUT_SECONDS)!=(constants['INSTRUCTIONS'],constants['CRITERIA'],constants['CRITERIA_VERSION'],constants['KEV_TIMEOUT_SECONDS']):
    raise RuntimeError('Imported constants do not match AST-frozen current source')
if KEV_TIMEOUT_SECONDS!=3.0:
    raise RuntimeError(f'Expected unchanged 3.0 second timeout, got {KEV_TIMEOUT_SECONDS!r}')
base_url=get_settings().kev_base_url.rstrip('/')
if base_url!='http://127.0.0.1:18009':
    raise RuntimeError(f'Unexpected endpoint {base_url!r}')
cache_before=get_kev_provider.cache_info()._asdict()
factory_started=time.perf_counter()
provider=get_kev_provider()
provider_init_ms=round((time.perf_counter()-factory_started)*1000,3)
provider_again=get_kev_provider()
same_provider_instance=provider is provider_again
same_client_instance=provider.client is provider_again.client
if not same_provider_instance or not same_client_instance:
    raise RuntimeError('Cached factory did not return the same provider/client')
record={
 'event':'kev_v31_shared_client_previous_timeout_cases_once',
 'status':'running',
 'criteria_version':CRITERIA_VERSION,
 'source_hashes':source_files,
 'provider_source_sha256':source_hash,
 'cases_path':str(cases_path),
 'cases_sha256':cases_hash,
 'case_ids':target_ids,
 'case_count_expected':3,
 'timeout_seconds':KEV_TIMEOUT_SECONDS,
 'endpoint':base_url+'/v1/systemone',
 'runtime':{'python':sys.executable,'python_version':sys.version.replace('\n',' '),'cwd':str(pathlib.Path.cwd()),'environment_override':{'KEV_BASE_URL':base_url},'other_environment':'Inherited unchanged; not enumerated to avoid unrelated credentials.','provider_factory':'app.llm.kev_provider.get_kev_provider','factory_cache_before':cache_before,'factory_provider_cache_reuse':same_provider_instance,'client_instance_reused':same_client_instance,'provider_initialization_ms':provider_init_ms,'client_persistent_for_all_three_cases':True},
 'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'constants':constants,
 'requests':requests,
 'results':[]
}
result_path=evidence/'results.json'
def persist(): result_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
persist()
for case in cases:
    case_started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    tick=time.perf_counter()
    try:
        answer,raw=provider.decide(case['state'])
        elapsed=round((time.perf_counter()-tick)*1000,3)
        dumped=answer.model_dump(mode='json')
        record['results'].append({'case_id':case['id'],'expected_unchanged':case['expected'],'status':'success','actual_choice':dumped['choice'],'matches_original_expected':dumped['choice']==case['expected'],'probabilities':dumped['probabilities'],'service_latency_ms':raw.get('latency_ms'),'usage':raw.get('usage'),'elapsed_ms':elapsed,'started_utc':case_started,'raw_response':raw})
    except KevUnavailable as exc:
        elapsed=round((time.perf_counter()-tick)*1000,3)
        record['results'].append({'case_id':case['id'],'expected_unchanged':case['expected'],'status':'failed','elapsed_ms':elapsed,'started_utc':case_started,'error_type':type(exc).__name__,'error':str(exc)})
    persist()
    item=record['results'][-1]
    print(json.dumps({'case_id':item['case_id'],'status':item['status'],'expected_unchanged':item['expected_unchanged'],'actual_choice':item.get('actual_choice'),'elapsed_ms':item['elapsed_ms'],'service_latency_ms':item.get('service_latency_ms'),'error_type':item.get('error_type'),'error':item.get('error')},ensure_ascii=False),flush=True)
close_started=time.perf_counter()
provider.client.close()
record['client_close_ms']=round((time.perf_counter()-close_started)*1000,3)
get_kev_provider.cache_clear()
record['factory_cache_cleared_after_close']=get_kev_provider.cache_info().currsize==0
record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
record['source_hashes_after']={str(p.relative_to(root)):sha(p) for p in (provider_path,chat_path,main_path)}
record['sources_unchanged_during_run']=record['source_hashes_after']==source_files
record['case_count_completed']=len(record['results'])
record['successful_count']=sum(x['status']=='success' for x in record['results'])
record['failed_count']=sum(x['status']=='failed' for x in record['results'])
record['matches_original_expected_count']=sum(x.get('matches_original_expected',False) for x in record['results'])
record['status']='all_three_attempts_recorded' if len(record['results'])==3 and record['sources_unchanged_during_run'] else 'incomplete_or_source_changed'
persist()
if record['status']!='all_three_attempts_recorded': raise RuntimeError(record['status'])
print(json.dumps({'status':record['status'],'provider_initialization_ms':provider_init_ms,'same_cached_provider':same_provider_instance,'same_client':same_client_instance,'successful_count':record['successful_count'],'failed_count':record['failed_count'],'matches_original_expected_count':record['matches_original_expected_count'],'sources_unchanged':record['sources_unchanged_during_run'],'factory_cache_cleared_after_close':record['factory_cache_cleared_after_close']},ensure_ascii=False),flush=True)

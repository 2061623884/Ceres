import hashlib, json, os
from pathlib import Path
root=Path('work/ceres-v4-evaluation/run-03').resolve()
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
schedule=manifest['schedule']
rows=[]
for item in schedule:
 path=root/item['execution_id']/'result.json'
 result=json.loads(path.read_text(encoding='utf-8'))
 calls=result.get('judge',{}).get('calls',[])
 request=calls[0].get('request') if calls else None
 valid=isinstance(request,dict) and isinstance(request.get('messages'),list) and bool(request.get('model'))
 rows.append({'execution_id':item['execution_id'],'result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'judge_call_count':len(calls),'request_present':valid,'request_sha256':hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest() if valid else None})
tree=Path(manifest['tree'])
config={p:hashlib.sha256((tree/p).read_bytes()).hexdigest() for p in ('.env','backend/.env','Mercury/.env') if (tree/p).exists()}
aliases=('LLM_MODEL','MEMORY_MODEL','OPENAI_BASE_URL','OPENAI_API_KEY','KEV_BASE_URL','LLM_TIMEOUT','LLM_MAX_OUTPUT_TOKENS','SEMANTIC_MAX_STEPS','SEMANTIC_LOOKUP_BUDGET','SEMANTIC_TURN_TIMEOUT_SECONDS','BUSINESS_DATA_MODE','SOURCE_DATABASE_PATH')
environment={key:hashlib.sha256(os.environ[key].encode()).hexdigest() for key in aliases if key in os.environ}
config_mismatch=[key for key in sorted(set(config)|set(manifest['config_identity'])) if config.get(key)!=manifest['config_identity'].get(key)]
environment_mismatch=[key for key in sorted(set(environment)|set(manifest['environment_identity'])) if environment.get(key)!=manifest['environment_identity'].get(key)]
out={'planned':len(schedule),'result_files':len(rows),'valid_captured_requests':sum(row['request_present'] for row in rows),'single_judge_call_results':sum(row['judge_call_count']==1 for row in rows),'invalid_execution_ids':[row['execution_id'] for row in rows if not row['request_present'] or row['judge_call_count']!=1],'config_identity_match':not config_mismatch,'config_mismatch_paths':config_mismatch,'environment_identity_match':not environment_mismatch,'environment_mismatch_keys':environment_mismatch,'source_manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'results':rows}
Path(r'''work/ceres-v4-evaluation/evidence/diag-run01/judge-request-audit.json''').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:out[key] for key in ('planned','result_files','valid_captured_requests','single_judge_call_results','invalid_execution_ids','config_identity_match','config_mismatch_paths','environment_identity_match','environment_mismatch_keys','source_manifest_sha256')},ensure_ascii=False,indent=2))

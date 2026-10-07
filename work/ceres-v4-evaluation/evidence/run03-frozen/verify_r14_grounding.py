import json,sys
p=sys.argv[1]
obj=json.load(open(p,encoding='utf-8'))
check=next(c for c in obj['checks'] if c.get('path')=='grounding_evidence')
actual=check['actual']
parsed=json.loads(actual) if isinstance(actual,str) else actual
serialized=json.dumps(parsed,ensure_ascii=False)
print(json.dumps({'result_json_valid':True,'check_passed':check['passed'],'actual_type':type(actual).__name__,'grounding_json_loads':isinstance(actual,str),'parsed_entries':len(parsed),'contains_P-DEL-01':'P-DEL-01' in serialized},ensure_ascii=False))

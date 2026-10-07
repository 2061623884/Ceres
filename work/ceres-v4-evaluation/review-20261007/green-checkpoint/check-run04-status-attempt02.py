import hashlib,json
from collections import Counter
from pathlib import Path
root=Path.cwd(); run=root/'work/ceres-v4-evaluation/run-04'; out=root/'work/ceres-v4-evaluation/review-20261007/green-checkpoint'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
result_paths=sorted(run.glob('*/result.json'))
rows=[]
for path in result_paths:
 row=json.loads(path.read_text(encoding='utf-8'))
 rows.append({'path':str(path.relative_to(root)),'status':row.get('status')})
counts=Counter(row['status'] for row in rows)
summary_path=run/'summary.json'; before=sha(summary_path); summary=json.loads(summary_path.read_text(encoding='utf-8')); summary_counts=summary['counts']
active=[x for x in rows if x['status'] in {'preparing','running'}]
missing=[x['path'] for x in rows if not x['status']]
expected_distribution=len(result_paths)==100 and counts==Counter({'passed':76,'failed':24}) and not active and not missing
matches_summary=(summary['actual_executions']==100 and summary_counts['passed']==counts['passed'] and summary_counts['failed']==counts['failed'] and summary_counts['runner_failed']==0 and summary_counts['preparation_failed']==0 and summary_counts['not_executed']==0)
after=sha(summary_path)
check={'run_directory':'work/ceres-v4-evaluation/run-04','result_json_count':len(result_paths),'result_status_counts':dict(sorted(counts.items())),'preparing_or_running_results':active,'missing_status_results':missing,'summary_actual_executions':summary['actual_executions'],'summary_counts':summary_counts,'summary_file_sha256_before':before,'summary_file_sha256_after_read':after,'summary_unchanged_by_hash':before==after,'all_results_terminal_and_expected_distribution':expected_distribution,'matches_existing_summary':matches_summary,'passed':expected_distribution and matches_summary and before==after}
(out/'run04-status-check-attempt02.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(check,ensure_ascii=False,indent=2))
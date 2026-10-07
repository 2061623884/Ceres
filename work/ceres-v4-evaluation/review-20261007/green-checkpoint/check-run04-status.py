import hashlib,json
from collections import Counter
from pathlib import Path
root=Path.cwd(); run=root/'work/ceres-v4-evaluation/run-04'; out=root/'work/ceres-v4-evaluation/review-20261007/green-checkpoint'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
result_paths=sorted(run.glob('*/result.json'))
rows=[]
for path in result_paths:
    row=json.loads(path.read_text(encoding='utf-8'))
    rows.append({'path':str(path.relative_to(root)),'status':row.get('status'),'performance_passed_present':'performance_passed' in row})
counts=Counter(row['status'] for row in rows)
summary_path=run/'summary.json'; summary_before=sha(summary_path)
summary=json.loads(summary_path.read_text(encoding='utf-8'))
summary_counts=summary.get('counts')
active=[row for row in rows if row['status'] in {'preparing','running'}]
missing_status=[row['path'] for row in rows if not row['status']]
terminal={status:count for status,count in sorted(counts.items())}
check={
 'run_directory':'work/ceres-v4-evaluation/run-04',
 'result_json_count':len(result_paths),
 'result_status_counts':terminal,
 'preparing_or_running_results':active,
 'missing_status_results':missing_status,
 'summary_actual_executions':summary.get('actual_executions'),
 'summary_planned_executions':summary.get('planned_executions'),
 'summary_counts':summary_counts,
 'summary_file_sha256_before':summary_before,
 'summary_file_sha256_after_read':sha(summary_path),
 'summary_unchanged_by_hash':summary_before==sha(summary_path),
 'all_results_terminal_and_expected_distribution':len(result_paths)==100 and counts==Counter({'passed':76,'failed':24}) and not active and not missing_status,
 'matches_existing_summary':summary.get('actual_executions')==100 and summary_counts=={'passed':76,'failed':24},
}
(out/'run04-status-check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(check,ensure_ascii=False,indent=2))
import hashlib,json
from pathlib import Path
root=Path.cwd(); val=root/'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked-validation'
new=root/'work/ceres-v4-evaluation/review-20261007/acceptance-rechecked'
old=root/'work/ceres-v4-evaluation/acceptance'
run04=root/'work/ceres-v4-evaluation/run-04'
def load(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
new_a=load(new/'acceptance.json'); old_a=load(old/'acceptance.json'); run_s=load(run04/'summary.json')
new_f=load(new/'failures.json'); old_f=load(old/'failures.json')
api=new_a['api']; old_api=old_a['api']; n_a=api['counts']['passed']; n_total=api['actual_executions']; fully=api['fully_passed']; core=api['core_pass3']; hard=api['hard_constraints']
def failure_count(value):
    if isinstance(value,list): return len(value)
    if isinstance(value,dict):
        for key in ('failures','items','records'):
            if isinstance(value.get(key),list): return len(value[key])
    raise TypeError(f'unrecognized failures file shape: {type(value).__name__}')
new_failure_count=failure_count(new_f); old_failure_count=failure_count(old_f)
execution=load(val/'reporter-recheck-execution.json')
preflight=load(val/'validation-preflight.json')
md=(new/'acceptance.md').read_text(encoding='utf-8')
checks={
 'api_business_passed_76_of_100':n_a==76 and n_total==100 and api['counts']['failed']==24,
 'fully_passed_55_of_100':fully==55,
 'core_pass3_6_of_20':core['passed']==6 and core['total']==20,
 'hard_constraints_39_of_49':hard['all_satisfied']==39 and hard['produced_plan_executions']==49,
 'under_15s_134_of_162':new_a['turns_within_15s']==134 and new_a['timed_turns']==162 and api['reply_latency_ms']['samples']==162,
 'failures_45_and_unchanged_count':new_failure_count==45 and old_failure_count==45,
 'api_summary_matches_prior_exactly':api==old_api,
 'api_counts_match_source_summary':api['counts']==run_s['counts'] and api['actual_executions']==run_s['actual_executions'] and api['fully_passed']==run_s['fully_passed'],
 'performance_n_a_only_h20_r1':new_a['performance_not_applicable']==[{'execution_id':'H20-r1','business_status':'passed'}],
 'performance_measured_99':new_a['performance_measured_executions']==99,
 'fully_passed_with_timed_turns_54':new_a['fully_passed_with_timed_turns']==54,
 'markdown_discloses_134_162_54_99_and_h20_na':('134/162' in md and '54/99' in md and 'H20-r1' in md),
 'new_reporter_sha_matches_script':new_a['reporter_sha256']==sha(root/'scripts/eval_v4_record.py'),
 'unit_tests_14_passed':preflight['tests']['exit_code']==0 and b'Ran 14 tests' in (val/'reporter-tests.stderr.txt').read_bytes() and b'OK' in (val/'reporter-tests.stderr.txt').read_bytes(),
 'python_compile_passed':preflight['compile']['exit_code']==0,
 'source_code_hashes_unchanged':execution['source_code_hashes_unchanged'],
 'original_input_hashes_unchanged':execution['input_hashes_unchanged'],
 'index_unchanged_by_reporter':execution['index_paths_unchanged'],
 'reporter_command_succeeded':execution['exit_code']==0,
 'old_acceptance_files_unchanged':execution['input_hashes_before']['old_acceptance']==execution['input_hashes_after']['old_acceptance'],
 'run04_old_summary_hash_unchanged':execution['input_hashes_before']['run04']==execution['input_hashes_after']['run04'],
}
result={'new_report_directory':str(new.relative_to(root)).replace('\\','/'),'old_acceptance_directory':str(old.relative_to(root)).replace('\\','/'),
 'reporter_sha256':new_a['reporter_sha256'],'reporter_command_exit_code':execution['exit_code'],'reporter_stdout_sha256':execution['stdout_sha256'],'reporter_stderr_sha256':execution['stderr_sha256'],
 'input_hashes_before_after_equal':execution['input_hashes_unchanged'],'source_hashes_before_after_equal':execution['source_code_hashes_unchanged'],
 'original_failure_records_unchanged':new_f==old_f,'old_summary_fields':{'counts':run_s['counts'],'fully_passed':run_s['fully_passed'],'core_pass3':run_s['core_pass3']['passed'],'core_total':run_s['core_pass3']['total'],'hard_constraints':run_s['hard_constraints']},
 'new_metrics':{'business_passed':n_a,'actual_executions':n_total,'fully_passed':fully,'core_pass3':core['passed'],'core_total':core['total'],'hard_constraints_satisfied':hard['all_satisfied'],'hard_constraint_executions':hard['produced_plan_executions'],'within_15s':new_a['turns_within_15s'],'timed_turns':new_a['timed_turns'],'failures':new_failure_count,'performance_not_applicable':new_a['performance_not_applicable'],'performance_measured_executions':new_a['performance_measured_executions'],'fully_passed_with_timed_turns':new_a['fully_passed_with_timed_turns']},
 'checks':checks,'passed':all(checks.values()) and new_f==old_f}
(val/'acceptance-rechecked-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
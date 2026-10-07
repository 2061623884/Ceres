import importlib.util
from pathlib import Path
import sys
import unittest

repo = Path(__file__).resolve().parents[6]
scripts = repo / 'scripts'
sys.path.insert(0, str(scripts))
import eval_v4_judge as current_judge

old_root = repo / 'work/ceres-v4-evaluation/review-20261007/red-failure-pipeline/frozen-old'
old_path = old_root / 'eval_v4_record.py'
spec = importlib.util.spec_from_file_location('frozen_old_record_with_probes', old_path)
old_recorder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = old_recorder
spec.loader.exec_module(old_recorder)

probe_paths = [
    repo / 'work/ceres-v4-evaluation/diagnostics-run03',
    repo / 'work/ceres-v4-evaluation/diagnostics-run03-v2',
]
original_main = old_recorder.main
def main_with_legacy_probe_arguments():
    for path in probe_paths:
        sys.argv.extend(['--probe', str(path)])
    return original_main()
old_recorder.main = main_with_legacy_probe_arguments

test_path = scripts / 'test_eval_v4_record.py'
test_spec = importlib.util.spec_from_file_location('failure_pipeline_test_module', test_path)
test_module = importlib.util.module_from_spec(test_spec)
sys.modules[test_spec.name] = test_module
test_spec.loader.exec_module(test_module)
test_module.recorder = old_recorder

suite = unittest.TestSuite([test_module.AcceptanceTests('test_incomplete_batch_reaches_acceptance_without_model_calls')])
result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

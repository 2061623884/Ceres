import argparse
import importlib.util
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('--binding', choices=('judge', 'record'), required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[4]
scripts = repo / 'scripts'
sys.path.insert(0, str(scripts))
import eval_v4_judge as current_judge
import eval_v4_record as current_record

old_root = Path(__file__).resolve().parent / 'frozen-old'
old_path = old_root / ('eval_v4_judge.py' if args.binding == 'judge' else 'eval_v4_record.py')
old_name = 'frozen_old_' + args.binding
spec = importlib.util.spec_from_file_location(old_name, old_path)
old_module = importlib.util.module_from_spec(spec)
sys.modules[old_name] = old_module
spec.loader.exec_module(old_module)

test_path = scripts / 'test_eval_v4_record.py'
test_spec = importlib.util.spec_from_file_location('failure_pipeline_test_module', test_path)
test_module = importlib.util.module_from_spec(test_spec)
sys.modules[test_spec.name] = test_module
test_spec.loader.exec_module(test_module)
if args.binding == 'judge':
    test_module.judge = old_module
else:
    test_module.recorder = old_module

suite = unittest.TestSuite([test_module.AcceptanceTests('test_incomplete_batch_reaches_acceptance_without_model_calls')])
result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

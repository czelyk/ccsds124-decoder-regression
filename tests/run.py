"""Compile and replay the bounded ARM probe with pinned upstream sources."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lab import new_run, execute, find_tool, verify_recorded, finish
from bootstrap import bootstrap

p = argparse.ArgumentParser()
p.add_argument('--verify-only', action='store_true')
args = p.parse_args()
verified = verify_recorded()
if args.verify_only:
    print(f'{verified} packaged files verified')
    raise SystemExit(0)
deps = bootstrap()
config = json.loads((ROOT / 'package.json').read_text())
run, work = new_run()
env = os.environ.copy()
env['ARM_GCC'] = str(find_tool('arm-none-eabi-gcc', 'ARM_GCC'))
env['CCSDS124_SOURCE'] = str(deps / 'ccsds124')
env['ION_SOURCE'] = str(deps / 'ion/cfdp/library/libcfdpP.c')
execute([sys.executable, work / config['runner']], work, 'execution.log', env)
result = json.loads((work / config['result_file']).read_text())
if config['name'] == 'ccsds124-decoder-regression':
    assert len(result['cases']) == 8
    for case in result['cases']:
        assert all(x['matches'] and x['rc'] == 0 for x in case['no_loss'])
        last = case['one_known_erasure'][-1]
        assert last['rc'] == 0 and not last['matches']
    detail = {'independent_builds': 4, 'reception_configurations': 8,
              'known_false_guarantee_reproduced': True, 'no_loss_controls_passed': True}
else:
    assert result['actual_function_invocations'] == 128
    assert result['source_acceptances'] == 4
    assert result['modeled_promise_violations'] == 2
    assert result['durable_data_before_coverage_promise_violations'] == 0
    assert result['reconcile_before_continuing_promise_violations'] == 0
    detail = {key: result[key] for key in ('actual_function_invocations', 'source_acceptances',
                'modeled_promise_violations', 'durable_data_before_coverage_promise_violations',
                'reconcile_before_continuing_promise_violations')}
finish(run, dict({'pass': True, 'kind': config['scope'], 'packaged_files_verified': verified}, **detail))

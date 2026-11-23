"""Local audit of verification cadence and sensitivity to fault phase."""

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import unicorn

from run_local_verify import packets_at
from run_reference_budget import FAULTS, replay
from run_reference_loss import RECORDING, scenarios
from run_venus import COUNT, NO_FAULT, ROOT, STARTS, prepare_arm_run, write_csv
from lab import new_run

ARCHIVE = ROOT / 'evidence/decision-recheck'
GRID = tuple(range(10, 17))
SENDER_FIELDS = ('wire_bytes', 'wire_sha256', 'reference_count', 'retry_indices')
MATCH_FIELDS = (*SENDER_FIELDS, 'longest_gap', 'missing_samples', 'wrong_delivered')


def short_cases(fault):
    yield 'intact', ()
    yield 'at_fault', (fault,)
    yield 'burst_at_fault', (fault, fault + 1, fault + 2)


def run_slice(start, selected, limit, digest, *, periodic_control=None):
    _, gcc, flags, _, dut, data = prepare_arm_run(
        f'decision_recheck_{start}', extra_flags=('-DVENUS_LOCAL_VERIFY',))
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('Unexpected telemetry source')
    packets = packets_at(data, start)
    rows, screened = [], []
    if selected is None:
        configurations = [('verify', interval, True) for interval in GRID]
        fault_cases = ((NO_FAULT, 0), *FAULTS)
        loss_patterns = scenarios
    else:
        if periodic_control is not None:
            configurations = [('periodic', periodic_control, False)]
        else:
            configurations = [('periodic', 13, False), ('verify', selected, True)]
            if selected != 13:
                configurations.append(('verify', 13, True))
        fault_cases = tuple((index, 32) for index in range(70, 86))
        loss_patterns = short_cases
    for policy, interval, verify in configurations:
        intact = {}
        for fault, bit in fault_cases:
            phase = 'clean' if fault == NO_FAULT else ('after_check' if verify else 'periodic')
            intact[fault, bit] = replay(dut, packets, start, interval, False, phase, fault, bit,
                                        local_verify=verify)
        max_bytes = max(row['wire_bytes'] for row in intact.values())
        screened.append({'slice_start': start, 'policy': policy, 'interval': interval, 'cap': limit,
                         'max_bytes': max_bytes, 'over_cap_cases': sum(
                             row['wire_bytes'] > limit for row in intact.values())})
        if any(row['wrong_delivered'] for row in intact.values()):
            raise RuntimeError(f'Incorrect intact delivery at slice {start}, K={interval}')
        if selected is None and max_bytes > limit:
            continue
        for fault, bit in fault_cases:
            control = intact[fault, bit]
            phase = 'clean' if fault == NO_FAULT else ('after_check' if verify else 'periodic')
            for label, erased in loss_patterns(fault):
                result = (replay(dut, packets, start, interval, False, phase, fault, bit,
                                 local_verify=verify, erased_indices=erased) if erased else control)
                if any(result[field] != control[field] for field in SENDER_FIELDS):
                    raise RuntimeError(f'Erasure changed the sender stream at {start}+{fault}, {label}')
                if result['wrong_delivered'] or result['missing_samples'] < len(erased):
                    raise RuntimeError(f'Receiver invariant failed at {start}+{fault}, {label}')
                rows.append({'policy': policy, 'interval': interval, 'slice_start': start,
                             'fault_index': result['fault_index'], 'mask_bit': result['mask_bit'],
                             'scenario': label, 'cap': limit, 'over_cap': int(result['wire_bytes'] > limit),
                             'erased_references': result.get('erased_references', ''),
                             'erased_retries': result.get('erased_retries', ''),
                             'trailing_gap': result.get('trailing_gap', 0),
                             **{field: result[field] for field in MATCH_FIELDS}})
    stage = 'tuning' if selected is None else 'shifted positions'
    print(f'{stage}: finished slice {start}', flush=True)
    compiler = subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0]
    return compiler, flags, screened, rows


def key(row):
    return tuple('' if row[field] is None else str(row[field])
                 for field in ('slice_start', 'fault_index', 'mask_bit', 'scenario'))


def aggregate(rows):
    return {'cases': len(rows), 'worst_gap': max(row['longest_gap'] for row in rows),
            'missing': sum(row['missing_samples'] for row in rows),
            'maximum_bytes': max(row['wire_bytes'] for row in rows),
            'over_cap_rows': sum(row['over_cap'] for row in rows)}


def comparison(rows, base, candidates):
    output = {}
    for policy, interval in candidates:
        results = [row for row in rows if (row['policy'], row['interval']) == (policy, interval)]
        if len(results) != len(base) or {key(row) for row in results} != base.keys():
            raise RuntimeError('Incomplete matched cases')
        metrics = {}
        for label in ('all', *dict.fromkeys(row['scenario'] for row in results)):
            matched = results if label == 'all' else [row for row in results if row['scenario'] == label]
            deltas = [row['longest_gap'] - int(base[key(row)]['longest_gap']) for row in matched]
            direction = Counter((delta > 0) - (delta < 0) for delta in deltas)
            metrics[label] = {**aggregate(matched), 'shorter_equal_longer': [direction[-1], direction[0], direction[1]]}
        output[f'{policy}_{interval}'] = metrics
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare with the archived recheck')
    args = parser.parse_args()
    output, _ = new_run('decision_recheck')
    prior = json.loads((RECORDING / 'summary.json').read_text(encoding='utf-8'))
    with (RECORDING / 'cases.csv').open(encoding='utf-8', newline='') as csv_file:
        old = list(csv.DictReader(csv_file))
    selected_periodic = ROOT / 'evidence/retuned-periodic/cases.csv'
    retuned = json.loads(selected_periodic.with_name('summary.json').read_text(encoding='utf-8'))
    archive_hashes = {
        'reference-loss/cases.csv': hashlib.sha256((RECORDING / 'cases.csv').read_bytes()).hexdigest(),
        'retuned-periodic/cases.csv': hashlib.sha256(selected_periodic.read_bytes()).hexdigest(),
    }
    if archive_hashes != {'reference-loss/cases.csv': prior['cases_csv_sha256'],
                          'retuned-periodic/cases.csv': retuned['csv_sha256']['cases.csv']}:
        raise RuntimeError('Prior archive identity mismatch')
    caps = {int(row['slice_start']): int(row['byte_ceiling']) for row in old}
    old16 = {key(row): row for row in old if row['policy'] == 'verify_16'}
    with selected_periodic.open(encoding='utf-8', newline='') as csv_file:
        periodic13 = {key(row): row for row in csv.DictReader(csv_file) if row['period'] == '13'}
    with ProcessPoolExecutor(max_workers=len(STARTS)) as workers:
        def stage(selected, *, periodic_control=None):
            build_info, screening, rows = [], [], []
            jobs = [workers.submit(run_slice, start, selected, caps[start], prior['dataset_sha256'],
                                   periodic_control=periodic_control)
                    for start in STARTS]
            for job in jobs:
                compiler, flags, local_screening, local_rows = job.result()
                build_info.append({'compiler': compiler, 'flags': flags})
                screening.extend(local_screening)
                rows.extend(local_rows)
            if any(build != build_info[0] for build in build_info):
                raise RuntimeError('Non-matching compiler configurations')
            return build_info[0], screening, rows

        build, screening, training = stage(None)
        rows16 = [row for row in training if row['interval'] == 16]
        if len(rows16) != len(old16) or {key(row) for row in rows16} != old16.keys():
            raise RuntimeError('Incomplete K=16 regression')
        for row in rows16:
            if any(str(row[field]) != old16[key(row)][field] for field in MATCH_FIELDS):
                raise RuntimeError(f'Archived K=16 differs at {key(row)}')
        feasible = [interval for interval in GRID if all(
            row['over_cap_cases'] == 0 for row in screening if row['interval'] == interval)]
        if not feasible:
            raise RuntimeError('No feasible verification setting')
        tuning = {interval: aggregate([row for row in training if row['interval'] == interval])
                  for interval in feasible}
        selected = min(feasible, key=lambda k: (tuning[k]['worst_gap'], tuning[k]['missing'],
                                                tuning[k]['maximum_bytes'], k))
        print(f'Frozen verifier K={selected} before shifted replay', flush=True)
        write_csv(output / 'tuning_screen.csv', screening)
        write_csv(output / 'tuning_cases.csv', training)
        (output / 'frozen_selection.json').write_text(
            json.dumps({'grid': GRID, 'feasible': feasible, 'metrics': tuning, 'selected': selected},
                       indent=2) + '\n', encoding='utf-8', newline='\n')
        _, shifted_screen, shifted = stage(selected)
        _, _, periodic11 = stage(selected, periodic_control=11)
    base = {key(row): row for row in shifted if row['policy'] == 'periodic'}
    candidates = list(dict.fromkeys((row['policy'], row['interval']) for row in shifted))
    write_csv(output / 'shifted_screen.csv', shifted_screen)
    write_csv(output / 'shifted_cases.csv', shifted)
    write_csv(output / 'shifted_periodic11.csv', periodic11)
    summary = {
        **build, 'unicorn': unicorn.__version__, 'source_samples_per_case': COUNT,
        'physical_measurements': False, 'dataset_sha256': prior['dataset_sha256'],
        'archive_hashes': archive_hashes, 'training_cases': len(training),
        'shifted_cases': len(shifted), 'verified_archived_k16_cases': len(rows16),
        'selected_verifier': selected, 'tuning_metrics': tuning,
        'training_comparison': comparison(training, periodic13, [('verify', selected)]),
        'shifted_comparison': comparison(shifted, base, candidates),
    }
    serialized = json.dumps(summary, indent=2) + '\n'
    (output / 'summary.json').write_text(serialized, encoding='utf-8', newline='\n')
    vs_periodic11 = comparison(shifted + periodic11, {key(row): row for row in periodic11},
                               [*candidates, ('periodic', 11)])
    (output / 'vs-periodic11.json').write_text(json.dumps(vs_periodic11, indent=2) + '\n',
                                              encoding='utf-8', newline='\n')
    if args.check:
        expected = json.loads((ARCHIVE / 'summary.json').read_text(encoding='utf-8'))
        actual = json.loads(serialized)
        for field in actual.keys() - {'compiler', 'unicorn'}:
            if actual[field] != expected[field]:
                raise RuntimeError(f'Shifted replay differs in {field}: {output}')
        old_comparison = json.loads((ARCHIVE / 'comparison.json').read_text(encoding='utf-8'))
        for name, digest in old_comparison['csv_sha256'].items():
            if hashlib.sha256((output / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f'CSV digest differs for {name}: {output}')
        for policy, scenarios_vs_control in vs_periodic11.items():
            for scenario, result in scenarios_vs_control.items():
                previous = old_comparison['comparison'][policy][scenario]
                if (result['worst_gap'], result['missing'], result['shorter_equal_longer']) != (
                        previous['worst'], previous['missing'], previous['versus_periodic11']):
                    raise RuntimeError(f'K=11 matched comparison differs for {policy}, {scenario}')
        print('Archived phase-recheck cases and comparisons reproduced.')
    print(output)


if __name__ == '__main__':
    main()

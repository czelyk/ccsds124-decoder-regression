"""Select a feasible periodic interval using the frozen reference-loss matrix."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import subprocess

import unicorn

from run_local_verify import packets_at
from run_reference_budget import FAULTS, replay, score
from run_reference_loss import RECORDING, scenarios
from run_venus import COUNT, NO_FAULT, ROOT, STARTS, prepare_arm_run, write_csv
from lab import new_run

PERIODS = (5, 8, *range(10, 21), 25, 32, 50, 100)
SENDER = ('wire_bytes', 'wire_sha256', 'reference_count')
DELIVERY = ('longest_gap', 'missing_samples', 'wrong_delivered')
ARCHIVE = ROOT / 'evidence/retuned-periodic'


def case_key(row):
    fault, bit = row['fault_index'], row['mask_bit']
    return (str(row['slice_start']), '' if fault is None else str(fault),
            '' if bit is None else str(bit), row['scenario'])


def replay_slice(start, cap, dataset_digest, old_periodic):
    _, gcc, flags, _, dut, data = prepare_arm_run(f'retuned_periodic_{start}')
    if hashlib.sha256(data).hexdigest() != dataset_digest:
        raise RuntimeError('Telemetry dataset differs from the prior loss campaign')
    packets = packets_at(data, start)
    screening, rows = [], []
    faults = ((NO_FAULT, 0), *FAULTS)
    for period in PERIODS:
        intact = {}
        for fault, bit in faults:
            phase = 'clean' if fault == NO_FAULT else 'periodic'
            intact[fault, bit] = replay(dut, packets, start, period, False, phase, fault, bit)
        max_bytes = max(row['wire_bytes'] for row in intact.values())
        if any(row['wrong_delivered'] for row in intact.values()):
            raise RuntimeError(f'Incorrect packet delivered on intact link at {start}, K={period}')
        screening.append({'slice_start': start, 'period': period, 'byte_ceiling': cap,
                          'max_intact_bytes': max_bytes, 'feasible': int(max_bytes <= cap)})
        if max_bytes > cap:
            continue
        for fault, bit in faults:
            control = intact[fault, bit]
            phase = 'clean' if fault == NO_FAULT else 'periodic'
            for scenario, erased in scenarios(fault):
                result = (replay(dut, packets, start, period, False, phase, fault, bit,
                                 erased_indices=erased) if erased else control)
                if any(result[field] != control[field] for field in SENDER):
                    raise RuntimeError(f'Erasure changed the sender stream at {start}, K={period}, {scenario}')
                if result['wrong_delivered'] or result['missing_samples'] < len(erased):
                    raise RuntimeError(f'Receiver delivery invariant failed at {start}, K={period}, {scenario}')
                row = {
                    'slice_start': start, 'period': period, 'fault_index': result['fault_index'],
                    'mask_bit': result['mask_bit'], 'scenario': scenario,
                    'erased_indices': ' '.join(map(str, erased)),
                    'erased_references': result.get('erased_references', ''),
                    'trailing_gap': result.get('trailing_gap', 0),
                    **{field: result[field] for field in (*DELIVERY, *SENDER)},
                }
                if period == 12:
                    expected = old_periodic[case_key(row)]
                    fields = (*DELIVERY, *SENDER, 'erased_indices', 'erased_references', 'trailing_gap')
                    if any(str(row[field]) != expected[field] for field in fields):
                        raise RuntimeError(f'K=12 loss control differs at {case_key(row)}')
                rows.append(row)
    print(f'Completed slice {start}', flush=True)
    compiler = subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0]
    return compiler, flags, screening, rows


def choose(rows, feasible):
    if not feasible:
        raise RuntimeError('No periodic interval meets the declared byte ceiling')
    return min(feasible, key=lambda period: (*score([r for r in rows if r['period'] == period]), period))


def compare(rows, verification, selected):
    selected_rows = [row for row in rows if row['period'] == selected]
    periodic = {case_key(row): row for row in selected_rows}
    if len(periodic) != len(selected_rows):
        raise RuntimeError('Duplicate selected periodic cases')
    result = {}
    for policy in ('periodic', 'verify_16', 'verify_100'):
        candidates = (list(periodic.values()) if policy == 'periodic'
                      else [row for row in verification if row['policy'] == policy])
        if len(candidates) != len(periodic) or {case_key(row) for row in candidates} != periodic.keys():
            raise RuntimeError(f'Missing or duplicate matched cases for {policy}')
        by_scenario = {}
        for scenario in dict.fromkeys(r['scenario'] for r in candidates):
            group = [row for row in candidates if row['scenario'] == scenario]
            gaps = [int(row['longest_gap']) - periodic[case_key(row)]['longest_gap'] for row in group]
            direction = Counter((delta > 0) - (delta < 0) for delta in gaps)
            by_scenario[scenario] = {
                'cases': len(group),
                'worst_gap': max(int(row['longest_gap']) for row in group),
                'unavailable_samples': sum(int(row['missing_samples']) for row in group),
                'better_equal_worse': [direction[-1], direction[0], direction[1]],
            }
        result[policy] = by_scenario
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Reproduce the recorded results')
    args = parser.parse_args()
    previous = json.loads((RECORDING / 'summary.json').read_text(encoding='utf-8'))
    source = RECORDING / 'cases.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest() != previous['cases_csv_sha256']:
        raise RuntimeError('Reference-loss archive checksum mismatch')
    with source.open(encoding='utf-8', newline='') as table:
        verification = list(csv.DictReader(table))
    old_periodic = {case_key(row): row for row in verification if row['policy'] == 'periodic_12'}
    caps = {int(row['slice_start']): int(row['byte_ceiling']) for row in old_periodic.values()}

    screening, cases = [], []
    with ProcessPoolExecutor(max_workers=len(STARTS)) as workers:
        jobs = [workers.submit(replay_slice, start, caps[start], previous['dataset_sha256'], old_periodic)
                for start in STARTS]
        for job in jobs:
            compiler, flags, local_screening, local_cases = job.result()
            screening.extend(local_screening)
            cases.extend(local_cases)
    feasible = {start: {r['period'] for r in screening if r['slice_start'] == start and r['feasible']}
                for start in STARTS}
    globally_feasible = sorted(set.intersection(*feasible.values()))
    selected = choose(cases, globally_feasible)
    scores = {period: score([row for row in cases if row['period'] == period])
              for period in globally_feasible}

    run, _ = new_run('retuned_periodic')
    write_csv(run / 'screening.csv', screening)
    write_csv(run / 'cases.csv', cases)
    record = {
        'compiler': compiler, 'flags': flags, 'unicorn': unicorn.__version__,
        'dataset_sha256': previous['dataset_sha256'], 'loss_archive_sha256': previous['cases_csv_sha256'],
        'screening_cases': len(screening) * (1 + len(FAULTS)),
        'periodic_cases': len(cases), 'periodic_source_samples': len(cases) * COUNT,
        'globally_feasible_periods': globally_feasible, 'selected_period': selected,
        'global_scores_gap_missing_bytes': scores,
        'selected_per_slice': {start: choose([row for row in cases if row['slice_start'] == start], feasible[start])
                               for start in STARTS},
        'matched_comparison': compare(cases, verification, selected),
        'csv_sha256': {name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                       for name in ('screening.csv', 'cases.csv')},
        'physical_measurements': False,
    }
    serialized = json.dumps(record, indent=2) + '\n'
    (run / 'summary.json').write_text(serialized, encoding='utf-8', newline='\n')
    if args.check:
        expected = json.loads((ARCHIVE / 'summary.json').read_text(encoding='utf-8'))
        actual = json.loads(serialized)
        for field in actual.keys() - {'compiler', 'unicorn'}:
            if actual[field] != expected[field]:
                raise RuntimeError(f'{field} differs from the archived replay: {run}')
        print('Recorded cases and summary reproduced.')
    print(f'Selected periodic K={selected}; wrote {run}')


if __name__ == '__main__':
    main()

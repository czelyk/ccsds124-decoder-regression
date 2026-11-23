"""Replay the frozen sender fault cases with controlled downstream erasures."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import subprocess

import unicorn

from run_local_verify import packets_at
from run_reference_budget import FAULTS, replay
from run_venus import COUNT, NO_FAULT, ROOT, STARTS, prepare_arm_run, write_csv

PUBLISHED = ROOT / 'evidence/local-verify'
RECORDING = ROOT / 'evidence/reference-loss'
POLICIES = (('periodic_12', 12, False), ('verify_16', 16, True), ('verify_100', 100, True))
SENDER_FIELDS = ('wire_sha256', 'wire_bytes', 'reference_count', 'local_retries', 'retry_indices')
DELIVERY_FIELDS = ('longest_gap', 'missing_samples', 'wrong_delivered')


def scenarios(fault):
    yield 'intact', ()
    if fault == NO_FAULT:
        yield 'initial_reference_loss', (0,)
        yield 'regular_packet_loss', (101,)
    else:
        yield 'before_fault', (fault - 1,)
        yield 'at_fault', (fault,)
        yield 'after_fault', (fault + 1,)
        yield 'burst_at_fault', (fault, fault + 1, fault + 2)


def summarize(rows):
    groups = defaultdict(list)
    periodic = {}
    for row in rows:
        key = tuple(row[field] for field in ('slice_start', 'fault_index', 'mask_bit', 'scenario'))
        if row['policy'] == 'periodic_12':
            periodic[key] = row['longest_gap']
        groups[row['policy'], row['scenario']].append((key, row))

    summary = {}
    for (policy, scenario), group in groups.items():
        direction = Counter()
        for key, row in group:
            delta = row['longest_gap'] - periodic[key]
            direction[(delta > 0) - (delta < 0)] += 1
        summary.setdefault(policy, {})[scenario] = {
            'cases': len(group),
            'worst_gap': max(row['longest_gap'] for _, row in group),
            'unavailable_samples': sum(row['missing_samples'] for _, row in group),
            'cases_with_erased_retry': sum(bool(row['erased_retries']) for _, row in group),
            'cases_with_trailing_gap': sum(bool(row['trailing_gap']) for _, row in group),
            'longest_gap_better_equal_worse_than_periodic': [direction[-1], direction[0], direction[1]],
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare deterministic results with the archive')
    args = parser.parse_args()
    previous = json.loads((PUBLISHED / 'summary.json').read_text(encoding='utf-8'))
    periodic_budget = json.loads(
        (ROOT / 'evidence/reference-budget/summary.json').read_text(encoding='utf-8'))
    prior_csv = PUBLISHED / 'cases.csv'
    csv_digest = hashlib.sha256(prior_csv.read_bytes()).hexdigest()
    if csv_digest != previous['cases_csv_sha256']:
        raise RuntimeError('Intact-link recording checksum mismatch')
    with prior_csv.open(encoding='utf-8', newline='') as source:
        archived = {(row['slice_start'], row['period'], row['fault_index'], row['mask_bit']): row
                    for row in csv.DictReader(source)}

    run, gcc, flags, _, dut, data = prepare_arm_run(
        'reference_loss', extra_flags=('-DVENUS_LOCAL_VERIFY',))
    dataset_digest = hashlib.sha256(data).hexdigest()
    if dataset_digest != previous['dataset_sha256']:
        raise RuntimeError('The corpus differs from the intact-link replay')
    rows = []
    for start in STARTS:
        packets = packets_at(data, start)
        cap = periodic_budget['by_slice'][str(start)]['byte_ceiling']
        for policy, period, verify in POLICIES:
            for fault, bit in ((NO_FAULT, 0), *FAULTS):
                phase = 'clean' if fault == NO_FAULT else ('after_check' if verify else 'periodic')
                fault_label, bit_label = ('', '') if fault == NO_FAULT else (str(fault), str(bit))
                expected = archived[str(start), str(period), fault_label, bit_label]
                for scenario, erased in scenarios(fault):
                    result = replay(dut, packets, start, period, False, phase, fault, bit,
                                    local_verify=verify, erased_indices=erased)
                    fields = SENDER_FIELDS if erased else SENDER_FIELDS + DELIVERY_FIELDS
                    if any(str(result[field]) != expected[field] for field in fields):
                        raise RuntimeError(f'Archived control mismatch at {start}, {policy}, {fault}, {scenario}')
                    if result['wire_bytes'] > cap or result['wrong_delivered']:
                        raise RuntimeError(f'Byte budget or delivery gate failed: {result}')
                    if result['missing_samples'] < len(erased):
                        raise RuntimeError(f'Erased samples were counted as delivered: {result}')
                    rows.append({
                        'policy': policy, 'scenario': scenario, 'slice_start': start,
                        'fault_index': result['fault_index'], 'mask_bit': result['mask_bit'],
                        'erased_indices': ' '.join(map(str, erased)),
                        'erased_references': result.get('erased_references', ''),
                        'erased_retries': result.get('erased_retries', ''),
                        'trailing_gap': result.get('trailing_gap', 0),
                        'byte_ceiling': cap,
                        **{field: result[field] for field in (*DELIVERY_FIELDS, *SENDER_FIELDS)},
                    })
        print(f'Completed slice {start}', flush=True)

    case_csv = run / 'cases.csv'
    write_csv(case_csv, rows)
    record = {
        'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
        'unicorn': unicorn.__version__, 'flags': flags, 'physical_measurements': False,
        'dataset_sha256': dataset_digest, 'intact_cases_sha256': csv_digest,
        'cases_csv_sha256': hashlib.sha256(case_csv.read_bytes()).hexdigest(),
        'cases': len(rows), 'source_samples': len(rows) * COUNT,
        'wrong_delivered': sum(row['wrong_delivered'] for row in rows),
        'by_policy_and_scenario': summarize(rows),
    }
    (run / 'summary.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.check:
        expected = json.loads((RECORDING / 'summary.json').read_text(encoding='utf-8'))
        for field in ('dataset_sha256', 'intact_cases_sha256', 'cases_csv_sha256', 'by_policy_and_scenario'):
            if record[field] != expected[field]:
                raise RuntimeError(f'{field} differs from the archived run: {run}')
        print('Recorded cases and summary reproduced.')
    print(run)


if __name__ == '__main__':
    main()

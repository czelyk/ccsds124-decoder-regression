"""Measure sender round-trip verification against the frozen periodic comparison."""
import argparse
import csv
import hashlib
import json
import subprocess

from run_reference_budget import FAULTS, replay, score
from run_venus import COUNT, PACKET_BYTES, ROOT, STARTS, prepare_arm_run, write_csv

LOCAL_PERIODS = (16, 100)
PROFILE_INDICES = (100, 101, 102)
PROFILE_FAULT = (101, 32)
LEGACY = ROOT / 'evidence/reference-budget'


def linked_sections(gcc, elf):
    tool = gcc.with_name('arm-none-eabi-size' + gcc.suffix)
    output = subprocess.check_output([str(tool), '-A', str(elf)], text=True)
    sections = dict((parts[0], int(parts[1])) for line in output.splitlines()
                    if (parts := line.split()) and parts[0] in ('.text', '.data', '.bss'))
    if '.text' not in sections or '.bss' not in sections:
        raise RuntimeError('Could not read linked ARM sections')
    return {name: sections.get(name, 0) for name in ('.text', '.data', '.bss')}


def packets_at(data, start):
    return [data[index * PACKET_BYTES:(index + 1) * PACKET_BYTES] for index in range(start, start + COUNT)]


def archived_cases(record):
    path = LEGACY / 'cases.csv'
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['csv_sha256']:
        raise RuntimeError('The archived periodic comparison changed')
    with path.open(encoding='utf-8', newline='') as source:
        rows = list(csv.DictReader(source))
    return {(int(row['slice_start']), int(row['period']), row['fault_index'], row['mask_bit']): row
            for row in rows if row['guarded'] == '0'}


def check_archived(row, archived):
    expected = archived[(row['slice_start'], row['period'], str_or_blank(row['fault_index']),
                         str_or_blank(row['mask_bit']))]
    for field in ('wire_bytes', 'longest_gap', 'missing_samples', 'wrong_delivered', 'wire_sha256'):
        if str(row[field]) != expected[field]:
            raise RuntimeError(f'Fresh periodic result differs in {field}: {row}')


def str_or_blank(value):
    return '' if value is None else str(value)


def compare(base, local, cap):
    gaps = [trial['longest_gap'] - comparator['longest_gap']
            for trial, comparator in zip(local[1:], base[1:], strict=True)]
    return {
        'fits_ceiling': score(local)[2] <= cap,
        'worst_gap': score(local)[0], 'missing_samples': score(local)[1], 'max_bytes': score(local)[2],
        'wrong_delivered': sum(r['wrong_delivered'] for r in local),
        'retries': sum(r['local_retries'] for r in local),
        'cases_with_retry': sum(r['local_retries'] > 0 for r in local),
        'gap_cases_better_equal_worse': [sum(d < 0 for d in gaps), sum(d == 0 for d in gaps),
                                         sum(d > 0 for d in gaps)],
    }


def profile(dut, packets, local_verify):
    rows = {}
    for phase in ('clean', 'late_fault'):
        counts = dict.fromkeys(PROFILE_INDICES)
        args = () if phase == 'clean' else ('after_check', *PROFILE_FAULT)
        row = replay(dut, packets, 0, 16, False, *args, local_verify=local_verify,
                     instruction_counts=counts)
        rows[phase] = {'sender_instructions': {str(index): count for index, count in counts.items()},
                       'retry_indices': row['retry_indices']}
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare deterministic evidence with the recorded run')
    args = parser.parse_args()
    frozen = json.loads((LEGACY / 'summary.json').read_text(encoding='utf-8'))
    archived = archived_cases(frozen)
    _, gcc, _, base_elf, base_dut, data = prepare_arm_run('local_verify_baseline')
    run, _, flags, local_elf, local_dut, _ = prepare_arm_run(
        'local_verify', extra_flags=('-DVENUS_LOCAL_VERIFY',))
    if hashlib.sha256(data).hexdigest() != frozen['dataset_sha256']:
        raise RuntimeError('Baseline and local test must use the same telemetry record')
    rows, by_slice = [], {}
    for start in STARTS:
        packets = packets_at(data, start)
        limits = frozen['by_slice'][str(start)]
        base_period = limits['best_fixed_period']
        cap = limits['byte_ceiling']
        baseline = [replay(base_dut, packets, start, base_period, False, local_verify=False)]
        for fault, bit in FAULTS:
            baseline.append(replay(base_dut, packets, start, base_period, False, 'periodic', fault, bit,
                                   local_verify=False))
        for row in baseline:
            check_archived(row, archived)
        if score(baseline)[2] > cap:
            raise RuntimeError('Frozen periodic comparator exceeds the stated ceiling')
        rows.extend(baseline)
        by_slice[str(start)] = {'byte_ceiling': cap, 'periodic_period': base_period,
                               'periodic_worst_gap': score(baseline)[0],
                               'periodic_missing_samples': score(baseline)[1],
                               'periodic_max_bytes': score(baseline)[2], 'local_verify': {}}
        for period in LOCAL_PERIODS:
            trials = [replay(local_dut, packets, start, period, False, local_verify=True)]
            check_archived(trials[0], archived)
            for fault, bit in FAULTS:
                trials.append(replay(local_dut, packets, start, period, False, 'after_check', fault, bit,
                                     local_verify=True))
            rows.extend(trials)
            by_slice[str(start)]['local_verify'][str(period)] = compare(baseline, trials, cap)
        print(f'Completed slice {start}', flush=True)

    base_sections, local_sections = linked_sections(gcc, base_elf), linked_sections(gcc, local_elf)
    profiles = {'periodic': profile(base_dut, packets_at(data, 0), False),
                'local_verify': profile(local_dut, packets_at(data, 0), True)}
    csv_path = run / 'cases.csv'
    write_csv(csv_path, rows)
    record = {
        'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
        'local_flags': flags, 'base_elf_sha256': hashlib.sha256(base_elf.read_bytes()).hexdigest(),
        'local_elf_sha256': hashlib.sha256(local_elf.read_bytes()).hexdigest(),
        'dataset_sha256': frozen['dataset_sha256'], 'periodic_source_csv_sha256': frozen['csv_sha256'],
        'cases_csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'physical_measurements': False, 'cases': len(rows), 'frames': len(rows) * COUNT,
        'wrong_delivered': sum(row['wrong_delivered'] for row in rows), 'by_slice': by_slice,
        'linked_sections': {'periodic': base_sections, 'local_verify': local_sections,
                            'delta': {name: local_sections[name] - base_sections[name] for name in base_sections}},
        'profile_slice': 0, 'profile_period': 16, 'profile_fault': list(PROFILE_FAULT),
        'instruction_profiles': profiles,
    }
    (run / 'summary.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.check:
        expected = json.loads((ROOT / 'evidence/local-verify/summary.json').read_text(encoding='utf-8'))
        for key in ('by_slice', 'cases_csv_sha256', 'dataset_sha256'):
            if record[key] != expected[key]:
                raise RuntimeError(f'{key} differs from the archived run: {run}')
        # Compare the linked sizes and instruction counts only for the recorded compiler.
        if record['compiler'] == expected['compiler']:
            for key in ('linked_sections', 'instruction_profiles'):
                if record[key] != expected[key]:
                    raise RuntimeError(f'{key} differs from the archived run: {run}')
    print(json.dumps(record, indent=2))
    print(run)


if __name__ == '__main__':
    main()

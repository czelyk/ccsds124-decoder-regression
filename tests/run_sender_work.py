"""Profile the cost of swapping verified decoder state against the archived implementation."""
import argparse
import csv
import hashlib
import json
import math
import subprocess

import unicorn

from run_local_verify import linked_sections, packets_at
from run_reference_budget import FAULTS, replay
from run_venus import COUNT, ROOT, STARTS, prepare_arm_run, write_csv

LOCAL_FLAGS = ('-DVENUS_LOCAL_VERIFY',)
SWAP_FLAGS = (*LOCAL_FLAGS, '-DVENUS_VERIFY_SWAP')
POLICIES = {
    'periodic': (12, ()),
    'verify_copy': (16, LOCAL_FLAGS),
    'verify_swap': (16, SWAP_FLAGS),
    'verify_swap_fixed': (16, (*SWAP_FLAGS, '-DVENUS_VERIFY_FIXED_COPY')),
}
ARCHIVE = ROOT / 'evidence/local-verify'
PROFILE_ARCHIVE = ROOT / 'evidence/sender-work'
MATCH_FIELDS = ('wire_sha256', 'wire_bytes', 'reference_count', 'missing_samples', 'longest_gap',
                'wrong_delivered', 'local_attempts', 'local_retries', 'retry_indices')


def load_baseline():
    summary = json.loads((ARCHIVE / 'summary.json').read_text(encoding='utf-8'))
    cases = (ARCHIVE / 'cases.csv').read_bytes()
    if hashlib.sha256(cases).hexdigest() != summary['cases_csv_sha256']:
        raise RuntimeError('Archived local verification cases changed')
    rows = csv.DictReader(cases.decode('utf-8').splitlines())
    return summary, {(r['slice_start'], r['period'], r['fault_index'], r['mask_bit']): r for r in rows}


def verify_case(row, expected):
    for field in MATCH_FIELDS:
        if str(row[field]) != expected[field]:
            raise RuntimeError(f'Archived {field} differs for replay {row}')


def profile_slice(dut, data, start, policy, period, baseline):
    packets = packets_at(data, start)
    verify = policy != 'periodic'
    profiles = []
    for fault in (None, *FAULTS):
        if fault is None:
            fault_index, mask_bit = '', ''
            args = ()
            indices = range(COUNT)
        else:
            fault_index, mask_bit = fault
            args = ('after_check' if verify else 'periodic', fault_index, mask_bit)
            indices = (fault_index,)
        packet_rows = []
        row = replay(dut, packets, start, period, False, *args, local_verify=verify,
                     instruction_counts=dict.fromkeys(indices), profile_rows=packet_rows)
        verify_case(row, baseline[(str(start), str(period), str(fault_index), str(mask_bit))])
        if len(packet_rows) != len(indices):
            raise RuntimeError('Unexpected number of profiled packets')
        for packet in packet_rows:
            profiles.append({
                'policy': policy, 'slice_start': start, 'period': period,
                'fault_index': fault_index, 'mask_bit': mask_bit, **packet,
            })
    return profiles


def summarize_packets(packets):
    instructions = sorted(row['instructions'] for row in packets)
    if not instructions:
        return {'count': 0}
    return {
        'count': len(instructions),
        'min_instructions': instructions[0],
        'p50_instructions': instructions[math.ceil(len(instructions) * 0.50) - 1],
        'p95_instructions': instructions[math.ceil(len(instructions) * 0.95) - 1],
        'max_instructions': instructions[-1],
        'max_wire_bytes': max(row['wire_bytes'] for row in packets),
    }


def summarize(rows):
    profiles = {}
    for policy in POLICIES:
        group = [row for row in rows if row['policy'] == policy]
        clean = [row for row in group if row['fault_index'] == '']
        faulted = [row for row in group if row['fault_index'] != '']
        profiles[policy] = {
            'clean_delta': summarize_packets([row for row in clean if not row['reference']]),
            'clean_reference': summarize_packets([row for row in clean if row['reference']]),
            'injected_sample_retry': summarize_packets([row for row in faulted if row['retry']]),
            'injected_sample_no_retry': summarize_packets([row for row in faulted if not row['retry']]),
        }
    return profiles


def paired_savings(rows, policy):
    copied = [r for r in rows if r['policy'] == 'verify_copy']
    swapped = [r for r in rows if r['policy'] == policy]
    fields = ('slice_start', 'fault_index', 'mask_bit', 'sample', 'retry', 'reference', 'wire_bytes')
    pairs = []
    for copy, swap in zip(copied, swapped, strict=True):
        if any(copy[k] != swap[k] for k in fields):
            raise RuntimeError('Verifier profiles are not paired')
        pairs.append((copy['instructions'] - swap['instructions'], bool(copy['retry'])))
    return {
        'min_instructions_saved': min(saved for saved, _ in pairs),
        'max_instructions_saved': max(saved for saved, _ in pairs),
        'min_retry_instructions_saved': min(saved for saved, retry in pairs if retry),
        'max_retry_instructions_saved': max(saved for saved, retry in pairs if retry),
    }


def disassemble(gcc, elf):
    objdump = gcc.with_name('arm-none-eabi-objdump' + gcc.suffix)
    output = subprocess.check_output([str(objdump), '-d', '--disassemble=verify_wire', str(elf)], text=True)
    marker = '<verify_wire>:'
    if marker not in output:
        raise RuntimeError('Could not locate verify_wire in the linked ARM image')
    return output[output.rindex('\n', 0, output.index(marker)) + 1:].rstrip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare with recorded profiling results')
    args = parser.parse_args()
    baseline_summary, baseline_cases = load_baseline()
    rows, linked, assembly = [], {}, []
    for policy, (period, flags) in POLICIES.items():
        run, gcc, build_flags, elf, dut, data = prepare_arm_run('sender_work_' + policy, extra_flags=flags)
        if hashlib.sha256(data).hexdigest() != baseline_summary['dataset_sha256']:
            raise RuntimeError('Profiling corpus differs from the baseline')
        linked[policy] = {'flags': build_flags, **linked_sections(gcc, elf)}
        if policy != 'periodic':
            assembly.append(f'[{policy}]\n{disassemble(gcc, elf)}')
        for start in STARTS:
            rows.extend(profile_slice(dut, data, start, policy, period, baseline_cases))
            print(f'Profiled {policy}, slice {start}', flush=True)

    csv_path = run / 'packets.csv'
    write_csv(csv_path, rows)
    assembly_path = run / 'verify-wire.txt'
    assembly_path.write_text('\n\n'.join(assembly) + '\n', encoding='utf-8', newline='\n')
    record = {
        'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
        'unicorn': unicorn.__version__,
        'dataset_sha256': baseline_summary['dataset_sha256'],
        'baseline_cases_sha256': baseline_summary['cases_csv_sha256'],
        'packets_csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'verify_wire_sha256': hashlib.sha256(assembly_path.read_bytes()).hexdigest(),
        'physical_measurements': False,
        'replayed_cases': len(POLICIES) * len(STARTS) * (1 + len(FAULTS)),
        'profiled_packets': len(rows),
        'linked_sections': linked,
        'instruction_profiles': summarize(rows),
        'swap_savings': {policy: paired_savings(rows, policy)
                         for policy in ('verify_swap', 'verify_swap_fixed')},
    }
    (run / 'summary.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.check:
        expected = json.loads((PROFILE_ARCHIVE / 'summary.json').read_text(encoding='utf-8'))
        if record != expected:
            raise RuntimeError(f'Profiling results differ from the archived build or tool versions: {run}')
    print(json.dumps(record, indent=2))
    print(run)


if __name__ == '__main__':
    main()

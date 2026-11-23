"""Measure sender instructions and stack-pointer depth at the same cadence."""

import argparse
import csv
import hashlib
import json
import subprocess
from math import ceil

import unicorn
from unicorn.arm_const import UC_ARM_REG_SP

from run_decision_recheck import ARCHIVE, key
from run_local_verify import linked_sections, packets_at
from run_reference_budget import replay
from run_venus import COUNT, NO_FAULT, ROOT, STARTS, prepare_arm_run, write_csv

COST_ARCHIVE = ROOT / 'evidence/matched-sender-cost'
POLICIES = {'periodic': (), 'verify': ('-DVENUS_LOCAL_VERIFY',)}


def measure_prepare(dut, depths):
    count = 0
    entry_sp = minimum_sp = None

    def sample(uc, *_):
        nonlocal count, entry_sp, minimum_sp
        stack_pointer = uc.reg_read(UC_ARM_REG_SP)
        if entry_sp is None:
            entry_sp = minimum_sp = stack_pointer
        minimum_sp = min(minimum_sp, stack_pointer)
        count += 1

    hook = dut.u.hook_add(unicorn.UC_HOOK_CODE, sample)
    try:
        dut.u.ctl_flush_tb()
        rc = dut.call('prepare_packet')
    finally:
        dut.u.hook_del(hook)
        dut.u.ctl_flush_tb()
    if entry_sp is None or dut.u.reg_read(UC_ARM_REG_SP) != entry_sp:
        raise RuntimeError('Sender did not execute with a balanced stack')
    depths.append(entry_sp - minimum_sp)
    return (dut.call('receive_wire') if rc == 0 else rc), count


def profile_case(dut, packets, start, policy, interval, fault, expected):
    verify = policy == 'verify'
    clean = fault == NO_FAULT
    phase = 'clean' if clean else ('after_check' if verify else 'periodic')
    bit = 0 if clean else 32
    indices = range(COUNT) if clean else (fault,)
    rows, depths = [], []
    result = replay(dut, packets, start, interval, False, phase, fault, bit,
                    local_verify=verify, instruction_counts=dict.fromkeys(indices),
                    profile_rows=rows, prepare_counter=lambda core: measure_prepare(core, depths))
    fields = ('wire_bytes', 'wire_sha256', 'missing_samples', 'longest_gap', 'wrong_delivered', 'retry_indices')
    if expected is not None and any(str(result[field]) != expected[field] for field in fields):
        raise RuntimeError(f'Profiling changed intact behavior at {start}+{fault}, {policy}')
    if clean and (result['missing_samples'] or result['wrong_delivered'] or result['local_retries']):
        raise RuntimeError(f'Clean profile failed at {start}, {policy}')
    if len(rows) != len(indices):
        raise RuntimeError('Unexpected number of profiled packets')
    return result['wire_sha256'], [
        {'policy': policy, 'slice_start': start, 'fault_index': '' if clean else fault,
         **row, 'sender_stack_depth_bytes': depth}
        for row, depth in zip(rows, depths, strict=True)
    ]


def summarize(rows):
    out = {}
    for policy in POLICIES:
        grouped = {'clean_delta': [], 'clean_reference': [], 'injected': [], 'retry': []}
        for row in (r for r in rows if r['policy'] == policy):
            if row['fault_index'] == '':
                grouped['clean_reference' if row['reference'] else 'clean_delta'].append(row)
            else:
                grouped['injected'].append(row)
                if row['retry']:
                    grouped['retry'].append(row)
        out[policy] = {}
        for label, group in grouped.items():
            counts = sorted(row['instructions'] for row in group)
            out[policy][label] = {'count': len(group)}
            if group:
                out[policy][label].update(
                    median_instructions=counts[ceil(len(counts) / 2) - 1],
                    max_instructions=counts[-1],
                    max_stack_depth_bytes=max(row['sender_stack_depth_bytes'] for row in group),
                )
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the recorded profile')
    args = parser.parse_args()
    selection = json.loads((ARCHIVE / 'frozen_selection.json').read_text(encoding='utf-8'))
    interval = selection['selected']
    prior = json.loads((ARCHIVE / 'summary.json').read_text(encoding='utf-8'))
    archive = json.loads((ARCHIVE / 'comparison.json').read_text(encoding='utf-8'))
    index = {}
    for file in ('shifted_cases.csv', 'shifted_periodic11.csv'):
        raw = (ARCHIVE / file).read_bytes()
        if hashlib.sha256(raw).hexdigest() != archive['csv_sha256'][file]:
            raise RuntimeError(f'Archive identity mismatch for {file}')
        index.update({(row['policy'], key(row)): row
                      for row in csv.DictReader(raw.decode('utf-8').splitlines())
                      if int(row['interval']) == interval and row['scenario'] == 'intact'})

    rows, builds, clean_digests = [], {}, {}
    for policy, options in POLICIES.items():
        run, gcc, flags, elf, dut, data = prepare_arm_run(f'matched_sender_cost_{policy}', extra_flags=options)
        if hashlib.sha256(data).hexdigest() != prior['dataset_sha256']:
            raise RuntimeError('Telemetry source differs from the decision recheck')
        builds[policy] = {
            'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
            'flags': flags, 'sections': linked_sections(gcc, elf),
        }
        for start in STARTS:
            packets = packets_at(data, start)
            for fault in (NO_FAULT, *range(70, 86)):
                expected = None if fault == NO_FAULT else index[policy, (str(start), str(fault), '32', 'intact')]
                digest, profiles = profile_case(dut, packets, start, policy, interval, fault, expected)
                if fault == NO_FAULT:
                    if start in clean_digests and clean_digests[start] != digest:
                        raise RuntimeError('Clean streams differ at the same cadence')
                    clean_digests[start] = digest
                rows.extend(profiles)
            print(f'{policy}: profiled slice {start}', flush=True)

    csv_path = run / 'packets.csv'
    write_csv(csv_path, rows)
    totals = {
        'builds': builds, 'unicorn': unicorn.__version__, 'interval': interval,
        'dataset_sha256': prior['dataset_sha256'], 'input_case_sha256': {
            file: archive['csv_sha256'][file] for file in ('shifted_cases.csv', 'shifted_periodic11.csv')},
        'clean_wire_sha256': clean_digests, 'physical_measurements': False,
        'profiled_packets': len(rows), 'packets_csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'measurements': summarize(rows),
    }
    serialized = json.dumps(totals, indent=2) + '\n'
    (run / 'summary.json').write_text(serialized, encoding='utf-8', newline='\n')
    if args.check and json.loads(serialized) != json.loads(
            (COST_ARCHIVE / 'summary.json').read_text(encoding='utf-8')):
        raise RuntimeError(f'Profile differs from archived build: {run}')
    print(serialized)
    print(run)


if __name__ == '__main__':
    main()

"""Compare periodic and mask-CRC-triggered references at a common byte ceiling."""
import argparse
import hashlib
import json
import struct
import subprocess
import zlib

from run_venus import COUNT, NO_FAULT, PACKET_BYTES, ROOT, STARTS, prepare_arm_run
from run_venus import read_word, set_word, write_csv

PERIODIC = (5, 8, 10, 12, 16, 20, 25, 32, 50, 100)
GUARDED = (16, 100)
FAULTS = tuple((index, bit) for index in (23, 61, 101, 158) for bit in (32, 511))
PHASES = ('before_check', 'after_check')


def replay(dut, packets, start, period, guarded, phase='clean', fault=NO_FAULT, bit=0):
    for name, value in (('reference_period', period), ('inject_at', fault), ('inject_bit', bit),
                        ('protect_mask', int(guarded)), ('inject_after_check', int(phase == 'after_check'))):
        set_word(dut, name, value)
    if dut.call('initialize') != 0:
        raise RuntimeError('Codec initialization failed')

    missing = current_gap = longest_gap = wrong_delivered = wire_bytes = references = mask_bytes = 0
    trigger_indices = []
    digest = hashlib.sha256()
    for index, packet in enumerate(packets):
        dut.u.mem_write(dut.names['input_bytes'], packet)
        if dut.call('exchange') != 0:
            raise RuntimeError(f'C exchange failed at {start}+{index}, K={period}, phase={phase}')
        size = read_word(dut, 'encoded_bytes') + 4
        bits = read_word(dut, 'encoded_bits')
        wire = bytes(dut.u.mem_read(dut.names['wire_bytes'], size))
        tag = int.from_bytes(wire[-4:], 'little')
        if tag != zlib.crc32(packet):
            raise RuntimeError('Source CRC differs from the input oracle')
        output = bytes(dut.u.mem_read(dut.names['basic_bytes'], PACKET_BYTES))
        parsed = read_word(dut, 'basic_rc', signed=True) == 0
        delivered = read_word(dut, 'basic_delivered') == 1
        if delivered != (parsed and zlib.crc32(output) == tag):
            raise RuntimeError('Receiver delivery differs from the independent CRC check')
        correct = delivered and output == packet
        if index < fault and not correct:
            raise RuntimeError(f'Incorrect control or pre-fault output at {start}+{index}, K={period}')
        wrong_delivered += int(delivered and not correct)
        missing += int(not correct)
        current_gap = 0 if correct else current_gap + 1
        longest_gap = max(longest_gap, current_gap)
        wire_bytes += size
        references += read_word(dut, 'reference_sent')
        mask_bytes += read_word(dut, 'mask_bytes_checked')
        if read_word(dut, 'forced_reference'):
            if not read_word(dut, 'reference_sent'):
                raise RuntimeError('Mask trigger failed to produce a full reference')
            trigger_indices.append(index)
        digest.update(struct.pack('<I', bits))
        digest.update(wire)

    flipped = read_word(dut, 'flipped_from')
    if not (flipped == NO_FAULT if fault == NO_FAULT else flipped in (0, 1)):
        raise RuntimeError('Fault injection indicator differs from the declared case')
    expected_triggers = [fault] if guarded and phase == 'before_check' else []
    if trigger_indices != expected_triggers:
        raise RuntimeError(f'Unexpected trigger indices: {trigger_indices}, wanted {expected_triggers}')
    return {
        'slice_start': start, 'period': period, 'guarded': int(guarded), 'phase': phase,
        'fault_index': None if fault == NO_FAULT else fault, 'mask_bit': None if fault == NO_FAULT else bit,
        'flipped_from': None if fault == NO_FAULT else flipped, 'triggers': len(trigger_indices),
        'reference_count': references, 'wire_bytes': wire_bytes, 'missing_samples': missing,
        'longest_gap': longest_gap, 'wrong_delivered': wrong_delivered,
        'mask_bytes_checked': mask_bytes, 'wire_sha256': digest.hexdigest(),
    }


def score(rows):
    return (max(row['longest_gap'] for row in rows), sum(row['missing_samples'] for row in rows),
            max(row['wire_bytes'] for row in rows))


def summarize(rows):
    summary = {}
    for start in STARTS:
        local = [row for row in rows if row['slice_start'] == start]
        budget = next(row['wire_bytes'] for row in local
                      if row['period'] == 10 and not row['guarded'] and row['phase'] == 'clean')
        periodic = {period: [r for r in local if not r['guarded'] and r['period'] == period]
                    for period in PERIODIC}
        feasible = {period: group for period, group in periodic.items() if score(group)[2] <= budget}
        if not feasible:
            raise RuntimeError(f'No periodic comparator fits the ceiling for slice {start}')
        best = min(feasible, key=lambda period: score(feasible[period]))
        baseline = feasible[best]
        record = {'byte_ceiling': budget, 'best_fixed_period': best,
                  'periodic_worst_gap': score(baseline)[0], 'periodic_missing_samples': score(baseline)[1],
                  'periodic_max_bytes': score(baseline)[2], 'guarded': {}}
        for period in GUARDED:
            group = [row for row in local if row['guarded'] and row['period'] == period]
            clean = next(row for row in group if row['phase'] == 'clean')
            base_clean = next(row for row in periodic[period] if row['phase'] == 'clean')
            if clean['wire_sha256'] != base_clean['wire_sha256']:
                raise RuntimeError('The guard changed clean wire data at the same periodic cadence')
            phases = {}
            for phase in PHASES:
                cases = [row for row in group if row['phase'] == phase]
                gaps, missing, peak = score(cases)
                deltas = [case['longest_gap'] - reference['longest_gap']
                          for case, reference in zip(cases, baseline[1:], strict=True)]
                phases[phase] = {'worst_gap': gaps, 'missing_samples': missing, 'max_bytes': peak,
                                 'triggers': sum(row['triggers'] for row in cases),
                                 'cases_better_equal_worse': [sum(d < 0 for d in deltas),
                                                              sum(d == 0 for d in deltas),
                                                              sum(d > 0 for d in deltas)]}
            for late, base in zip([row for row in group if row['phase'] == 'after_check'],
                                  periodic[period][1:], strict=True):
                if late['wire_sha256'] != base['wire_sha256']:
                    raise RuntimeError('The undetected late fault differs from the same-period control')
            record['guarded'][str(period)] = {'fits_ceiling_in_all_cases': score(group)[2] <= budget,
                                             'clean_bytes': clean['wire_bytes'],
                                             'mask_bytes_checked_per_packet': clean['mask_bytes_checked'] // COUNT,
                                             **phases}
        summary[str(start)] = record
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare deterministic output with the archived run')
    args = parser.parse_args()
    run, gcc, flags, elf, dut, data = prepare_arm_run('reference_budget')
    rows = []
    for start in STARTS:
        packets = [data[index * PACKET_BYTES:(index + 1) * PACKET_BYTES]
                   for index in range(start, start + COUNT)]
        for period in PERIODIC:
            rows.append(replay(dut, packets, start, period, False))
            for fault, bit in FAULTS:
                rows.append(replay(dut, packets, start, period, False, 'periodic', fault, bit))
        for period in GUARDED:
            rows.append(replay(dut, packets, start, period, True))
            for phase in PHASES:
                for fault, bit in FAULTS:
                    rows.append(replay(dut, packets, start, period, True, phase, fault, bit))
        print(f'Completed slice {start}', flush=True)

    csv_path = run / 'cases.csv'
    write_csv(csv_path, rows)
    record = {
        'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
        'flags': flags,
        'elf_sha256': hashlib.sha256(elf.read_bytes()).hexdigest(),
        'dataset_sha256': hashlib.sha256(data).hexdigest(),
        'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'physical_measurements': False,
        'cases': len(rows), 'frames': len(rows) * COUNT,
        'wrong_delivered': sum(row['wrong_delivered'] for row in rows),
        'periodic_grid': PERIODIC, 'guarded_periods': GUARDED, 'faults': FAULTS,
        'by_slice': summarize(rows),
    }
    (run / 'summary.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.check:
        archived = json.loads((ROOT / 'evidence/reference-budget/summary.json').read_text(encoding='utf-8'))
        for key in ('by_slice', 'csv_sha256', 'dataset_sha256'):
            if archived[key] != record[key]:
                raise RuntimeError(f'{key} differs from the archived run: {run}')
    print(json.dumps(record['by_slice'], indent=2))
    print(run)


if __name__ == '__main__':
    main()

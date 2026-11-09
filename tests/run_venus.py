"""Execute the bounded Venus Express encoder-state matrix on Cortex-M4."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from bootstrap import bootstrap
from lab import execute, find_tool, new_run

PACKET_BYTES = 90
STARTS = (0, 75_000, 150_176)
PERIODS = (10, 100)
BITS = (0, 31, 32, 63, 64, 127, 255, 511, 719)
COUNT = 224
FAULT_INDEX = 101
NO_FAULT = 0xffffffff
COMPONENTS = ('bitvector', 'decompress', 'bitbuffer', 'compress', 'encode', 'mask')


def set_word(dut, name, value):
    dut.u.mem_write(dut.names[name], struct.pack('<I', value))


def read_word(dut, name, signed=False):
    return int.from_bytes(dut.u.mem_read(dut.names[name], 4), 'little', signed=signed)


def longest_gap(rows, prefix=''):
    best = current = 0
    for row in rows:
        current = 0 if row[prefix + 'delivered'] and row[prefix + 'equal'] else current + 1
        best = max(best, current)
    return best


def stable_recovery(rows, prefix=''):
    last_missing = max((r['index'] for r in rows
                        if not (r[prefix + 'delivered'] and r[prefix + 'equal'])), default=-1)
    return last_missing + 1 if last_missing + 1 < COUNT else None


def replay(dut, packets, start, period, bit):
    set_word(dut, 'reference_period', period)
    set_word(dut, 'inject_at', NO_FAULT if bit is None else FAULT_INDEX)
    set_word(dut, 'inject_bit', 0 if bit is None else bit)
    if dut.call('initialize') != 0:
        raise RuntimeError('C codec initialization failed')

    rows = []
    wire_hash = hashlib.sha256()
    for index, packet in enumerate(packets):
        dut.u.mem_write(dut.names['input_bytes'], packet)
        if dut.call('exchange') != 0:
            raise RuntimeError(f'C frame setup failed at {start}+{index}, K={period}, bit={bit}')
        length = read_word(dut, 'encoded_bytes')
        valid_bits = read_word(dut, 'encoded_bits')
        rc = read_word(dut, 'decode_rc', signed=True)
        status = int(dut.u.mem_read(dut.names['decode_status'], 1)[0])
        source_crc = read_word(dut, 'source_crc')
        decoded_crc = read_word(dut, 'decoded_crc')
        delivered = read_word(dut, 'delivered')
        wire = bytes(dut.u.mem_read(dut.names['wire_bytes'], length + 4))
        if int.from_bytes(wire[-4:], 'little') != zlib.crc32(packet) or source_crc != zlib.crc32(packet):
            raise RuntimeError('C source checksum or serialization differs from zlib')
        wire_hash.update(struct.pack('<I', valid_bits))
        wire_hash.update(wire)
        guaranteed = rc == 0 and status == 0
        decoded = bytes(dut.u.mem_read(dut.names['decoded_bytes'], PACKET_BYTES))
        if guaranteed and decoded_crc != zlib.crc32(decoded):
            raise RuntimeError('C decoded checksum differs from zlib')
        if delivered != int(guaranteed and zlib.crc32(decoded) == source_crc):
            raise RuntimeError('C delivery gate differs from the independent checksum calculation')
        equal = int(guaranteed and decoded == packet)
        basic_rc = read_word(dut, 'basic_rc', signed=True)
        basic_crc = read_word(dut, 'basic_crc')
        basic_delivered = read_word(dut, 'basic_delivered')
        basic = bytes(dut.u.mem_read(dut.names['basic_bytes'], PACKET_BYTES))
        if basic_rc == 0 and basic_crc != zlib.crc32(basic):
            raise RuntimeError('Basic C checksum differs from zlib')
        if basic_delivered != int(basic_rc == 0 and zlib.crc32(basic) == source_crc):
            raise RuntimeError('Basic C delivery gate differs from the independent checksum calculation')
        basic_equal = int(basic_rc == 0 and basic == packet)
        if (bit is None or index < FAULT_INDEX) and not (equal and delivered and basic_equal and basic_delivered):
            raise RuntimeError(f'Clean control failed at {start}+{index}, K={period}, bit={bit}')
        rows.append({'slice_start': start, 'period': period, 'mask_bit': bit,
                     'index': index, 'reference_sent': read_word(dut, 'reference_sent'),
                     'encoded_bits': valid_bits, 'encoded_bytes': length,
                     'decoder_rc': rc, 'decoder_status': status, 'guaranteed': int(guaranteed),
                     'equal': equal, 'delivered': delivered, 'source_crc32': f'{source_crc:08x}',
                     'decoded_crc32': f'{decoded_crc:08x}' if guaranteed else None,
                     'basic_rc': basic_rc, 'basic_equal': basic_equal, 'basic_delivered': basic_delivered,
                     'basic_crc32': f'{basic_crc:08x}' if basic_rc == 0 else None})

    flipped = read_word(dut, 'flipped_from')
    if (bit is None and flipped != NO_FAULT) or (bit is not None and flipped not in (0, 1)):
        raise RuntimeError('C injection indicator differs from the declared case')
    record = {
        'slice_start': start, 'period': period, 'mask_bit': bit,
        'flipped_from': None if bit is None else flipped,
        'wrong_guaranteed_without_crc': sum(r['guaranteed'] and not r['equal'] for r in rows),
        'wrong_delivered_with_crc': sum(r['delivered'] and not r['equal'] for r in rows),
        'decoder_rejects': sum(not r['guaranteed'] for r in rows),
        'longest_gap_with_crc': longest_gap(rows),
        'stable_recovery_index': stable_recovery(rows),
        'basic_wrong_delivered_with_crc': sum(r['basic_delivered'] and not r['basic_equal'] for r in rows),
        'basic_longest_gap_with_crc': longest_gap(rows, 'basic_'),
        'basic_stable_recovery_index': stable_recovery(rows, 'basic_'),
        'payload_bytes': sum(r['encoded_bytes'] for r in rows),
        'payload_and_crc_bytes': sum(r['encoded_bytes'] + 4 for r in rows),
        'wire_sha256': wire_hash.hexdigest(),
    }
    return record, rows


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def prepare_arm_run(label, *, extra_flags=()):
    deps = bootstrap()
    bootstrap(lock_name='venus.dependencies.lock.json')
    gcc = find_tool('arm-none-eabi-gcc', 'ARM_GCC')
    run, work = new_run(label)
    vendor = deps / 'ccsds124'
    os.environ['ARM_GCC'] = str(gcc)
    os.environ['CCSDS124_SOURCE'] = str(vendor)
    sys.path.insert(0, str(work))
    from verify_counterexample import DUT

    flags = ['-mcpu=cortex-m4', '-mthumb', '-O2', '-std=c99', '-fwrapv',
             '-ffreestanding', '-fno-builtin', '-nostdlib', '-DCCSDS124_MAX_PACKET_LENGTH=720', *extra_flags]
    elf = work / 'venus.elf'
    execute([gcc, *flags, '-I' + str(vendor / 'include'), work / 'venus_state.c',
             *(vendor / 'src' / (name + '.c') for name in COMPONENTS),
             '-T', work / 'link.ld', '-lgcc', '-o', elf], work, 'build.log')
    dut = DUT(elf)

    data = (deps / 'data/venus-express.ccsds').read_bytes()
    if len(data) != 151_200 * PACKET_BYTES:
        raise RuntimeError('Unexpected Venus Express record size')
    return run, gcc, flags, elf, dut, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare measurements with the recorded matrix')
    args = parser.parse_args()
    run, gcc, flags, elf, dut, data = prepare_arm_run('venus')
    case_rows, frame_rows = [], []
    for start in STARTS:
        packets = [data[index * PACKET_BYTES:(index + 1) * PACKET_BYTES]
                   for index in range(start, start + COUNT)]
        for period in PERIODS:
            for bit in (None, *BITS):
                case, rows = replay(dut, packets, start, period, bit)
                case_rows.append(case)
                frame_rows.extend(rows)
        print(f'Completed slice {start}', flush=True)

    write_csv(run / 'cases.csv', case_rows)
    write_csv(run / 'frames.csv', frame_rows)
    by_period = {}
    for period in PERIODS:
        faulted = [c for c in case_rows if c['period'] == period and c['mask_bit'] is not None]
        next_reference = ((FAULT_INDEX // period) + 1) * period
        by_period[str(period)] = {
            'fault_cases': len(faulted),
            'cases_with_wrong_guaranteed': sum(c['wrong_guaranteed_without_crc'] > 0 for c in faulted),
            'wrong_guaranteed_without_crc': sum(c['wrong_guaranteed_without_crc'] for c in faulted),
            'wrong_delivered_with_crc': sum(c['wrong_delivered_with_crc'] for c in faulted),
            'maximum_gap_with_crc': max(c['longest_gap_with_crc'] for c in faulted),
            'basic_wrong_delivered_with_crc': sum(c['basic_wrong_delivered_with_crc'] for c in faulted),
            'basic_maximum_gap_with_crc': max(c['basic_longest_gap_with_crc'] for c in faulted),
            'stable_by_next_reference': sum(c['stable_recovery_index'] is not None and
                                            c['stable_recovery_index'] <= next_reference for c in faulted),
            'basic_stable_by_next_reference': sum(c['basic_stable_recovery_index'] is not None and
                                                  c['basic_stable_recovery_index'] <= next_reference for c in faulted),
            'clean_payload_and_crc_bytes': [c['payload_and_crc_bytes'] for c in case_rows
                                            if c['period'] == period and c['mask_bit'] is None],
        }
    measurements = {'cases': len(case_rows), 'frames': len(frame_rows), 'by_period': by_period}
    record = {
        'compiler': subprocess.check_output([str(gcc), '--version'], text=True).splitlines()[0],
        'flags': flags,
        'dataset_sha256': hashlib.sha256(data).hexdigest(),
        'elf_sha256': hashlib.sha256(elf.read_bytes()).hexdigest(),
        'cases_csv_sha256': hashlib.sha256((run / 'cases.csv').read_bytes()).hexdigest(),
        'frames_csv_sha256': hashlib.sha256((run / 'frames.csv').read_bytes()).hexdigest(),
        'slice_starts': list(STARTS), 'packets_per_case': COUNT, 'fault_index': FAULT_INDEX,
        'fault_bits': list(BITS), 'physical_measurements': False, 'measurements': measurements,
    }
    (run / 'summary.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.check:
        archived = json.loads((ROOT / 'evidence/venus-state/summary.json').read_text(encoding='utf-8'))
        for key in ('measurements', 'cases_csv_sha256', 'frames_csv_sha256', 'dataset_sha256'):
            if record[key] != archived[key]:
                raise RuntimeError(f'{key} differs from the archived run: {run}')
    print(json.dumps(measurements, indent=2))
    print(run)


if __name__ == '__main__':
    main()

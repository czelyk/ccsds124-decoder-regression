# Sender-side verification before telemetry transmission

Can a sender catch a wrong compressed sample after the point where a
mask check would already have passed, and recover within the same
serialized byte budget as periodic full references?

## Method

The sender snapshots its compressor state immediately before encoding,
after fault injection. It decodes the serialized payload into a trial
copy of a local decoder, checks exact payload-bit consumption and compares
all 90 decoded bytes with the source. It commits the local decoder state
only on success. On a failed encode or check, it restores the compressor
snapshot, forces both full-reference flags, and verifies the second
encoding of the same sample. If that fails, the fixture returns an error
before passing a payload to the receiver. No second failure was observed.
Restoring the snapshot retains the injected mask upset. The full reference
lets the receiver synchronize to the current encoder state.

The comparator is periodic K=12, the strongest feasible fixed setting
from the [previous byte-budget sweep](reference-budget.md). Its fresh wire
hashes, byte counts and delivery outcomes match the frozen comparison.
The verification runs use a periodic fallback of K=16 or K=100 with the
mask CRC disabled. Each policy replays the same three 224-sample Venus
Express slices with one clean case and eight separate accidental
mask-bit flips per slice. The bits are 32 and 511 at local sample
positions 23, 61, 101 and 158. Clean streams match the unguarded
streams at the same cadence byte for byte.

Each budget covers a complete slice and counts the byte-rounded compressed
payload plus the four-byte source CRC. Only the released payload counts
when the sender retries. The same source CRC and exact-bit-consumption
check gate delivery in every case. The experiment assumes intact, in-order
transport. The budgets exclude transport framing, length metadata and
channel coding.

## Results

The Cortex-M4 emulation executed 81 cases and 18,144 sample exchanges,
excluding profiling replays. No incorrect sample was delivered. Across the
24 matched fault cases, periodic K=12 left 102 samples unavailable and
had an 11-sample longest gap. Both verification settings delivered all
samples and stayed below the byte ceiling in every case.

| Slice start | Byte ceiling | Max bytes K=12 | Max bytes with verification K=16 | Max bytes with verification K=100 |
|---:|---:|---:|---:|---:|
| 0 | 13,664 | 13,273 | 12,892 | 11,827 |
| 75,000 | 11,410 | 11,016 | 10,613 | 9,506 |
| 150,176 | 12,245 | 11,854 | 11,458 | 10,376 |

Each verification setting retried on the injected sample in 22 of 24
fault cases. In the other two cases, all outputs matched throughout the
slice without a retry. Neither setting retried in the clean controls.

The linked fixture grew from 6,802 to 10,642 bytes of static RAM
(`.bss`) and from 11,656 to 12,080 bytes of code (`.text`). These
figures exclude peak stack use and include the fixture's receiver.
The profile compares matched K=16 builds on the first slice. At sample
101 the clean sender used 31,656 instructions without verification and
54,146 with verification. With a bit-32 fault at the same sample the
counts were 31,728 and 149,139, respectively. The latter includes the
full-reference retry. The [raw summary](../evidence/local-verify/summary.json)
also records the two neighboring samples. These are emulated instruction
counts from one short profile. MCU timing, energy and peak RAM remain
unmeasured.

## Limits

The result covers one telemetry file, one codec implementation and two
bit positions in the encoder mask. The trial decoder shares upstream
codec code with the receiver. The test assumes a trustworthy source
sample and local verifier state, a single upset before encoding, and
no loss or corruption after verification. A full reference can still
be lost on the link. Longer fallback periods may make that failure more
costly. A window-wide byte ceiling cannot establish that the extra
instructions and the larger retry packet fit a per-sample deadline or
link slot.

## Reproduce

Install the [repository prerequisites](../README.md#run) and run:

```sh
python tests/run_local_verify.py --check
```

The script writes a fresh case table and summary under `runs/` and
checks them against the archive. It also checks linked sections and
instruction counts when the compiler version matches the archived build.
See the [81 recorded cases](../evidence/local-verify/cases.csv).

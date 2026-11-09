# Sender work and decoder state copies

This experiment measures the cost of the sender-side decode check across
the [previous Venus Express replay](local-verify.md). It tests whether
the sender can remove one decoder state copy while preserving every
output and retry decision.

## Comparison

- Periodic K=12 is the strongest fixed setting from the
  [shared byte-budget sweep](reference-budget.md).
- The original verifier uses K=16. It copies the committed decoder state
  into a trial buffer before each decode and copies the trial back after
  a successful check.
- The indexed swap uses K=16. It seeds the trial using pointers selected
  by the active index, then commits success by toggling that index.
- The fixed-address swap uses the same policy. Each direction names both
  buffers explicitly at the remaining copy site. A failed trial leaves
  the active index unchanged in both swap builds.

The two swap builds isolate the practical impact of how GCC lowers the
remaining copy. Build options other than the experimental macros stay the
same. The compared verifier policies retain the same decoder check,
compressor rollback and full-reference retry.

Each build replays the clean control and all eight single-mask-bit
cases on three 224-sample slices. This yields 108 cases and 24,192 sample
exchanges. The script checks the wire hash, byte count, reference count,
correct delivery and retry decisions against the archived case for
every replay. It counts sender instructions in Unicorn for every clean
sample and for the injection sample of each fault case. The 2,784
profiled samples exclude receiver work. Clean full references are
reported separately from clean delta packets. The reported percentiles
use nearest rank.

## Results

Both swap builds matched the original verifier's complete wire streams
and its delivery and retry outcomes. Each retried in 22 of 24 fault
cases at the injection sample and left zero samples unavailable.

| Policy | Clean delta median instructions | Clean reference maximum | Retry maximum | Linked static RAM |
|---|---:|---:|---:|---:|
| Periodic K=12 | 28,913 | 57,205 | None | 6,802 B |
| Original verification K=16 | 48,389 | 137,240 | 153,665 | 10,642 B |
| Indexed swap K=16 | 49,265 | 138,116 | 155,853 | 10,650 B |
| Fixed-address swap K=16 | 47,957 | 136,808 | 153,235 | 10,650 B |

The indexed swap increased the median clean delta cost by 876
instructions. Its remaining 436-byte decoder state copy used byte
loads and stores. The original verifier and the fixed-address swap
used word loads and stores for this copy. The fixed-address swap
saved 428 to 433 instructions per paired sample compared with the
original verifier. The retry maximum fell by 430 instructions
(0.28 percent), with an extra 8 bytes of linked static RAM and 32
bytes of linked code. Removing the second copy therefore saved
little of the observed retry cost even with word-width copies.

The largest observed retry packet was 154 bytes. Planned full
references reached 246 bytes in the clean replay. Both counts include
the source CRC and exclude framing. The peaks for work and packet
size are reported separately. The linked RAM figures cover the entire
fixture, including its receiver, and exclude peak stack.

## Limits

These instruction counts describe the measured paths in one compiler
configuration. The exact changes depend on code generation, including the
fixture's copy implementation. The sampled maxima cover the three slices
and specified injection positions. They provide no bound for all source
streams or retry paths. The experiment assumes intact in-order
transport. It uses no physical MCU, interrupt load or real link schedule.
A deadline decision needs on-target cycle and peak stack measurements
under representative interrupt load, together with the actual byte
allowance of the transmit slot.

## Reproduce

Install the [repository prerequisites](../README.md#run) and run:

```sh
python tests/run_sender_work.py --check
```

The check expects the recorded Arm GNU Toolchain and Unicorn versions.
Omit `--check` to obtain fresh counts on a different toolchain. Each run
writes its results under `runs/`. The archive includes
[per-packet counts](../evidence/sender-work/packets.csv),
[a summary](../evidence/sender-work/summary.json) and
[the linked verifier disassembly](../evidence/sender-work/verify-wire.txt).

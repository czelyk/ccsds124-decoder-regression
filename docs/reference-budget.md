# Fault-triggered versus periodic full references

This experiment asks whether detecting an accidental encoder mask change
and sending an immediate full reference improves recovery under the same
serialized byte ceiling as periodic references.

## Comparison

The [Venus Express replay](venus-state-replay.md) supplies the same three
224-sample slices, pinned C codec, Cortex-M4 fixture and independent
byte/checksum oracle. Both policies use the ordinary decoder with exact
payload-bit consumption and a source CRC before application delivery. The
model delivers every frame intact.

- **Periodic:** test fixed reference periods 5, 8, 10, 12, 16, 20, 25, 32,
  50 and 100. Each case starts with three full references. The normal
  new-mask flag remains every 20 samples.
- **Guarded:** use a fixed fallback period of 16 or 100. Seal the encoder's
  mask words with a local CRC-32 at initialization and after compression.
  Compare the seal before the next encode. A mismatch forces both full
  reference flags for the current sample. The encoder sends the current mask
  with the original sample so the receiver can synchronize to the current
  state. The guard neither restores the old mask nor resets the codec.
- **Faults and controls:** run a clean control at each setting. Independently
  flip mask bit 32 or 511 at local sample 23, 61, 101 or 158. The guarded
  runs place the flip immediately before or immediately after the check,
  always before encoding. The periodic runs need one placement because
  neither placement crosses a check on that path.

The clean K=10 run defines a separate byte ceiling for each slice. Bytes
are the byte-rounded compressed payload and the four-byte source CRC,
including fault-triggered references. Transport framing, length metadata and
channel coding are excluded. The ceiling applies over the 224-sample window.
It represents a comparison budget, with no assumed mission requirement or
instantaneous link constraint.

The periodic comparator gets hindsight over the tested cases. For each
slice, choose one fixed period that fits the ceiling in every case and
minimizes the longest gap, then the total unavailable samples, then the
largest byte count. The guarded periods are fixed for all slices. A gap
counts consecutive samples that fail to reach the application correctly.

The guard CRC covers the mask storage words only. Other encoder state,
the seal itself, overlapping faults and reference loss are outside this
matrix. The two CRC passes process 184 mask-storage bytes per packet in
the tested build, plus the initial seal. That is a byte count for the CRC
input, with no measured MCU time or energy.

Full references and decoder resynchronization are established techniques.
This comparison isolates the effect of when a mask upset becomes visible to
the encoder's check. [CCSDS 124.0-B-1](https://ccsds.org/Pubs/124x0b1.pdf) ·
[Resynchronization study](https://doi.org/10.1109/ACCESS.2024.3374227)

## Results

The matrix executed 372 cases and 83,328 frame exchanges in Cortex-M4
emulation. None delivered an incorrect sample through the source-CRC gate.
Both guarded settings stayed under the ceiling in every tested case. The
periodic selection was K=12 on all three slices. Faulted K=10 streams
exceeded the clean K=10 ceiling by up to 10, 11 and 13 bytes, respectively,
so that period did not qualify under the strict budget rule.

| Slice start | Byte ceiling | Periodic K=12 worst gap | Guarded K=16 worst gap, before / after | Guarded K=100 worst gap, before / after |
|---:|---:|---:|---:|---:|
| 0 | 13,664 | 11 | 0 / 11 | 0 / 99 |
| 75,000 | 11,410 | 11 | 0 / 11 | 0 / 99 |
| 150,176 | 12,245 | 11 | 0 / 11 | 0 / 99 |

Each guarded setting detected all 24 before-check flips and delivered every
sample in those runs. Neither setting detected any of the 24 after-check
flips. The encoder resealed its updated mask after the late injection.
The emitted streams in those runs matched the unguarded same-period streams
byte for byte, as checked by the recorded wire-stream hashes. The clean
guarded streams also matched their same-period controls.

Across the 24 matched fault locations, periodic K=12 left 102 samples
unavailable. In the after-check runs, guarded K=16 left 120 unavailable and
guarded K=100 left 979. These are separate fault-placement controls. The
experiment supplies no probability for either placement. The long fallback
saved bytes but made the late-fault gap substantially longer. The shorter
fallback tied the periodic worst gap and left more samples unavailable in
the late-fault cases, while using fewer bytes. This leaves a conditional
recovery benefit and no measured improvement to the worst tested gap.

## Reproduce

Use the [repository prerequisites](../README.md#run) and run:

```sh
python tests/run_reference_budget.py --check
```

The command writes a fresh run under `runs/` and checks the case CSV hash
and summary against [the recorded results](../evidence/reference-budget/summary.json).
The [case CSV](../evidence/reference-budget/cases.csv) includes the serialized
wire-stream hash, reference count, delivery results and size for each run.

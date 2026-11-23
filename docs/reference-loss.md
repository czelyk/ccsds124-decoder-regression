# Receiver gaps after a dropped POCKET+ reference

Sender-side verification restored every sample in the earlier mask-fault replay when the link delivered every packet. This experiment tests how that result changes when an emitted packet never reaches the receiver.

The protocol keeps the three previously examined 224-sample Venus Express slices, the eight mask flips per slice, the original source CRC gate and the same slice byte ceilings. Compare periodic K=12 and sender verification at K=16 and K=100. Each policy uses the same source sample indices for erasures. After successful encoding at an erased index, the sender advances normally while the receiver is never called. The model provides no feedback and no explicit loss notification to the receiver. Surviving packets arrive intact and in order.

Clean-source controls erase nothing, one scheduled reference at index 0, or a regular packet at index 101. The fault cases erase nothing, one packet immediately before, at, or after the fault index, or three consecutive packets beginning at that index. Erasure at the fault index removes a repair reference if the sender produced one there. These are stress cases with equal packet indices across policies. They carry no assumed rates of mask faults or downlink loss.

Budget accounting counts every emitted byte, including erased packets. Each loss run must reproduce the intact sender's archived wire digest, byte count and retry count. Check intact receiver outcomes against the archived campaign. Score unavailable samples, longest consecutive gap and any incorrect application delivery. Report whether the erased frames were full references or local retries. A worse longest gap in any paired loss case defeats an unconditional recovery advantage. A zero-gap outcome in the original intact-link campaign cannot carry over to an erased packet.

CCSDS 124 defines packet-loss robustness and full mask transmission. Prior work evaluates decoder resynchronization and the cost of redundancy. Here the comparison couples the existing encoder-mask upset with a downstream erasure while preserving the existing receiver policy. [CCSDS 124.0-B-1](https://ccsds.org/Pubs/124x0b1.pdf) · [Hernández-Cabronero et al.](https://doi.org/10.1109/ACCESS.2024.3374227)

## Results

The Cortex-M4 emulation ran 387 cases and processed 86,688 source
samples. Every loss case matched its intact sender stream, including
its serialized byte count, SHA-256, reference count and retry indices.
Every case met the original per-slice byte ceiling. The receiver delivered
zero incorrect samples through the source CRC gate.

| Erasure condition | Cases per policy | Periodic K=12 worst gap | Verify K=16 worst gap | Verify K=100 worst gap |
| --- | ---: | ---: | ---: | ---: |
| Intact link, clean and mask-fault cases | 27 | 11 | 0 | 0 |
| First scheduled reference, clean source | 3 | 1 | 1 | 1 |
| Regular packet, clean source | 3 | 1 | 1 | 1 |
| One packet before the mask flip | 24 | 12 | 1 | 1 |
| Packet at the mask flip | 24 | 11 | 11 | 99 |
| One packet after the mask flip | 24 | 13 | 1 | 1 |
| Three packets starting at the mask flip | 24 | 13 | 18 | 99 |

The gap unit is consecutive unavailable source samples. Losing the packet
at the fault drops a full retry reference in 22 of the 24 fault cases for
each verification setting. With this erasure, K=16 has a longer gap than
the paired periodic case in 10 of 24 comparisons, a shorter gap in five,
and ties in nine. With the three-packet erasure, it is worse in seven and
better in nine. Its total unavailable count over those burst cases is
166 versus 181 for periodic, while its worst observed gap rises to 18.

In one K=100 case at slice start 0, the mask flip and erasure both occur at
local index 101. The erased full retry reference is followed by a 99-sample
unavailable run and recovery at the scheduled reference at 200. In one
K=16 case at slice start 150176, the three erasures at 158–160 remove both
the retry reference at 158 and the scheduled reference at 160. The receiver
recovers at 176 after an 18-sample gap. These are in-window outcomes.

## Engineering consequence

The zero-gap result depends on the repair reaching the receiver. The long
fallback can save bytes but worsens recovery if that repair is erased.
The shorter fallback reduces the penalty while still allowing worse
paired gaps. An unconditional recovery improvement fails this comparison.

These are deliberately aligned erasures on three previously examined slices
from one telemetry file. They do not estimate operational rates, and the
periodic comparator retains K=12 from the intact-link budget study. There
is no new sweep of cadence, robustness level or receiver policy under loss.
The link model has no timing, transport metadata, feedback or physical MCU
measurement. The results support a contingency to include in that larger
comparison if a documented link and data-availability requirement justify it.

## Reproduce

```sh
python tests/run_reference_loss.py --check
```

The runner records fresh outputs under `runs/` and checks the case-file
digest and aggregate results against the archived run. The raw table
identifies both erased full references and erased retries.
[Case table](../evidence/reference-loss/cases.csv) ·
[Summary](../evidence/reference-loss/summary.json)

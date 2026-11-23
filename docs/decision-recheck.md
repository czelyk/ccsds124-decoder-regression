# POCKET+ decision recheck

This local audit checks asymmetry in the published comparison. On the existing matrix, tune the verification interval over K=10 through K=16. Use the same slice ceilings and the same ranking rule as the published periodic comparison. Screen all nine intact cases for each interval and slice. Score feasible intervals on the same clean and fault cases, including the same erasures. First reproduce the archived K=16 results. Use previously selected periodic K=13 as the control.

After freezing the selected verifier, replay both policies at previously unused mask-fault positions 70 through 85 inclusive on all three original slices, with mask bit 32. Include verification at K=13 to isolate the effect of changing the implementation while holding cadence fixed. Each position has an intact control, a single erasure at the fault, and a three-packet burst starting there. Sixteen consecutive positions span all phases of K=13 and every verifier interval in the declared grid. These positions test sensitivity to phase on the same data. They do not constitute independent flight data. Keep the 224-sample horizon, the original byte ceilings, receiver and robustness settings. Count all emitted bytes before erasure. Report every over-budget case. Preserve each wire digest across paired intact and loss runs. The training grid spans the vicinity of the strongest periodic settings and includes the previously tested K=16 verification. It does not claim global optimization.

Reopen the longest-gap improvement claim only if a verification period selected without the new positions fits the existing caps and strictly shortens the worst gap on the new paired positions. Report paired wins and losses and total unavailable samples even if that gate fails. These counts do not weight cases by operational likelihood.

Before inspecting any shifted results, add a separate sensitivity control for periodic K=11. It tied K=13 on the old worst-gap metric and lost on total unavailable samples. This checks whether a strict win against K=13 would persist against the other pre-existing minimum-gap finalist. This control does not change the original selection rule or the verifier tuning grid.

## Results

The Cortex-M4 replay reproduced 129 prior K=16 verification cases.
Six verifier settings met all three ceilings. K=11 minimized the
longest gap on the tuning matrix at 10 samples. The earlier periodic
K=13 result was 11 samples on that matrix. K=10 failed all three
byte ceilings during screening.

On the shifted fault positions, each policy replayed the same 144 cases
across the same three Venus Express slices. All four policies fit the
byte ceilings and delivered zero incorrect samples.

| Shifted cases | Periodic K=13 | Verify K=13 | Periodic K=11 | Verify K=11 |
| --- | ---: | ---: | ---: | ---: |
| Longest gap, intact link | 10 | 0 | 7 | 0 |
| Longest gap, one packet erased | 10 | 10 | 7 | 7 |
| Longest gap, three packets erased | 13 | 13 | 10 | 10 |
| Unavailable samples, all 144 cases | 772 | 541 | 583 | 415 |

At the same K=11 cadence, the two methods agreed on longest gap and
number of unavailable samples in each of the 96 erasure cases. In the
48 intact cases, verification shortened the gap 42 times and tied six
times. The 168-sample reduction summed across these lab cases came
entirely from the intact-link runs. The longest-gap claim stays closed
against the two prior periodic finalists. The intact-link result
supports a separate availability trade-off, subject to a documented
mission scenario and target resource costs. The shifted positions
cover new phases on one previously studied file and one mask bit.

## Sender resource measurements at K=11

The resource replay builds the periodic sender and original copying
verifier separately. Both use the selected K=11 interval. It profiles
every clean packet and the injection packet at each shifted position.
The clean sent streams must be byte-identical. Faulted streams and
delivery outcomes must match the corresponding intact cases of the
phase recheck.

An emulator hook counts instructions and samples the stack pointer
before each instruction in `prepare_packet`. The reported stack
depth is the difference between its entry value and the minimum
sampled value. The hook also checks that the function restores its
entry stack pointer. Receiver work, interrupt frames and any caller
stack below the entry point are outside the measurement. These are
observed emulated costs for the recorded compiler and inputs.

| Observed sender metric | Periodic K=11 | Verify K=11 |
| --- | ---: | ---: |
| Median instructions, clean delta | 28,920 | 48,366 |
| Maximum instructions, clean reference | 60,102 | 137,240 |
| Maximum instructions, injection packet | 42,854 | 153,408 |
| Maximum sampled stack depth below sender entry | 256 B | 6,780 B |
| Linked fixture static RAM | 6,802 B | 10,642 B |

The run profiled 1,440 packets. Verification added about 67% to
median clean-delta instructions and reached 6,524 additional bytes
of observed sender stack depth. The linked static RAM totals include
the receiver fixture and exclude stack. The verify build's disassembly
shows 3,748 bytes reserved in `ccsds124_decompress_packet_internal` and
a further 2,880 bytes reserved by its nested `ccsds124_bit_insert` path,
before saved registers and other frames. The cost therefore depends on
the decoder implementation and compiler. These sampled paths supply
neither a hardware deadline nor a worst-case stack bound.

For this build, the intact-link improvement buys availability at a
material sender cost. The erased-repair cases show the same gaps as
the periodic sender at the same interval. A case for adopting the
verifier would need to justify the intact-link gain under an actual
availability and resource budget.

## Reproduce

```sh
python tests/run_decision_recheck.py --check
python tests/run_matched_sender_cost.py --check
```

The runner writes new outputs below `runs/` and checks the case
tables and comparisons against the original local audit.
[Tuning matrix](../evidence/decision-recheck/tuning_cases.csv) ·
[Shifted cases](../evidence/decision-recheck/shifted_cases.csv) ·
[Periodic K=11 control](../evidence/decision-recheck/shifted_periodic11.csv) ·
[Matched comparison](../evidence/decision-recheck/comparison.json) ·
[Resource summary](../evidence/matched-sender-cost/summary.json) ·
[Packet profiles](../evidence/matched-sender-cost/packets.csv)

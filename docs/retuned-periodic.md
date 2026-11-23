# Periodic references tuned against packet loss

Freeze the original mask faults, downstream erasures, source CRC gate,
three 224-sample Venus Express slices, and per-slice byte ceilings from
the [reference-loss experiment](reference-loss.md). Compare the archived
sender verification at K=16 and K=100 with periodic reference intervals
from 10 through 20 inclusive and the original settings 5, 8, 25, 32, 50,
and 100. The denser grid covers the area around the previous K=12 choice.
The CCSDS robustness parameter, mask update cadence, and decoder stay fixed.

Screen each interval with all nine intact-link cases per slice. Charge
every emitted byte including erased packets. Downstream erasure has no
feedback to the sender, so an over-budget intact stream cannot become
feasible after an erasure. Replay every loss pattern for each interval
that fits a slice. Check that wire size, wire digest and reference count
match its freshly replayed intact control. Also check the K=12 control
against the prior loss campaign before comparing the archived verifiers.

Select one periodic interval feasible on all three slices. Minimize the
longest gap, then the sum of unavailable samples, then the maximum
number of emitted bytes across cases, then the interval itself. Report
single-slice choices as a sensitivity check, and compare the selected
periodic interval with each verifier on the same slice, fault and loss
indices. Score the longest gap over the whole matrix, with paired
win/tie/loss counts and total missing samples as secondary measures.

The slices and loss placements were studied before this replay. A winning
setting describes this bounded matrix. Selection by minimizing the
same matrix gives the periodic method hindsight, and the scores are not
independent validation or estimates of flight loss rates.

## Executed result

The Cortex-M4 emulation screened 459 intact cases over 17 intervals and
three slices. Fourteen intervals met all three byte ceilings. Feasible
settings contributed 1,806 scored cases, including 378 intact cases
reused from screening. All 129 K=12 cases matched the prior loss
archive. No replay delivered an incorrect sample.

K=13 and K=11 both minimized the longest gap at 11 samples.
K=13 won the declared tie-break with 374 unavailable samples across its
129 cases versus 688 for K=11. Using each slice separately also selected
K=13. Its maximum serialized totals across the three slices were
13,176, 10,910 and 11,753 bytes, under ceilings of 13,664, 11,410 and
12,245 bytes. Those ceilings include every emitted payload and its source
CRC, including packets the receiver never gets.

| Metric | Periodic K=13 | Verify K=16 | Verify K=100 |
| --- | ---: | ---: | ---: |
| Longest gap, all cases | 11 | 18 | 99 |
| Longest gap, intact cases | 4 | 0 | 0 |
| Longest gap, erasure at the fault index | 4 | 11 | 99 |
| Longest gap, three erasures starting at the fault index | 11 | 18 | 99 |
| Unavailable samples, summed across 129 cases | 374 | 342 | 2,108 |
| Shorter / tied / longer gaps against K=13 | 0 / 129 / 0 | 76 / 33 / 20 | 66 / 33 / 30 |

K=16 yields fewer unavailable samples in this unweighted matrix, while
K=13 gives the shorter worst gap. The summed count describes the
selected cases and carries no estimate of how often their loss patterns
occur. The verifier comparisons use recorded runs from the same
erasure matrix and unchanged sender and receiver code.

## Decision and scope

Sender verification did not shorten the longest gap against the
retuned periodic baseline. This closes the current worst-gap improvement
claim. The intact-link advantage and the error-recovery cost trade-off
remain documented. A mission-specific case would need a measured or
specified loss profile, a justified availability metric, and on-target
resource measurements. In particular, K=13 is fitted to these fault and
loss placements. The study holds the CCSDS robustness level and decoder
policy fixed, and provides no general ranking of recovery policies.

## Reproduce

```sh
python tests/run_retuned_periodic.py --check
```

The runner generates a fresh result under `runs/`. Its checks compare
the deterministic case and screening digests and the selected metrics
with the archived run. [All periodic cases](../evidence/retuned-periodic/cases.csv) ·
[Byte screening](../evidence/retuned-periodic/screening.csv) ·
[Comparison summary](../evidence/retuned-periodic/summary.json)

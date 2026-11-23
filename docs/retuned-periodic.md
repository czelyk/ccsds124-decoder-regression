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

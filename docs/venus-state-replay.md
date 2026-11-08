# Venus Express encoder-state replay

This bounded experiment exercises a single accidental mask bit flip inside
the compressor. It measures whether the checked decoder labels wrong data
as guaranteed, whether a CRC over the original sample filters that output,
and how reference cadence and receiver policy affect recovery.

## Inputs and procedure

- Use three 224-packet slices of one published Venus Express telemetry file
  starting at packet indices 0, 75,000 and 150,176. The file contains
  151,200 records of 90 bytes. The [pinned corpus metadata](https://github.com/tanagraspace/ccsds124/blob/a049cfeec1900414be5b9fc0c18c49436cbb3c82/test-vectors/expected-output/venus-express-metadata.json)
  and [dataset description](https://github.com/tanagraspace/ccsds124#test-vectors)
  identify the input. The lock file verifies the on-demand download.
  The repository contains no telemetry payload bytes.
- Use the pinned TanagraSpace C codec with a 720-bit packet limit and
  robustness 2. Enable the new-mask flag at every 20th local index. Send
  full references at indices 0, 1 and 2, and every `K` thereafter, with
  `K = 10` or `K = 100`. Each case starts with fresh codec state.
- Just before encoding local index 101, flip one bit of the stored encoder
  mask. Exercise positions 0, 31, 32, 63, 64, 127, 255, 511 and 719 separately.
  Retain a clean control for every slice and period. The matrix has 54 fault
  cases and six controls on one mission record. No upset probability is assumed.
- Compute a CRC-32 over the original sample before compression. Append its
  four little-endian bytes after the byte-rounded compressed payload in a
  lab-only envelope. The decoder receives the exact valid payload bit count.
  The model delivers each packet with its payload and tag unchanged.
- The checked path with CRC requires guaranteed status and checksum agreement.
  The basic path uses the upstream ordinary decoder, requires exact bit
  consumption, commits state on a complete parse and checks the same CRC
  before delivery. CRC rejection does not roll back a completed parse.
  Python independently checks C checksums, delivery decisions and bytes.

The ARM GNU build uses `-fwrapv` to define wrapping behavior for signed
negation in the pinned encoder's low-bit extraction. Upstream sources are
unchanged. The codec and both receiver paths run as Cortex-M4 instructions
in Unicorn. Python supplies the inputs and verifies the outputs. The
envelope is a test fixture. Physical timing and radiation effects are outside
the experiment.

## Recorded result

| Full reference period | Wrong outputs called guaranteed before CRC | Wrong outputs delivered with CRC (either path) | Longest checked-path gap | Longest basic-path gap | Stable by next reference, checked / basic |
|---:|---:|---:|---:|---:|---:|
| 10 | 142 | 0 | 19 | 9 | 3 / 27 |
| 100 | 576 | 0 | 99 | 99 | 22 / 27 |

A gap counts consecutive unusable samples. Stable recovery means every
remaining sample through index 223 was delivered correctly. Both paths
delivered all 1,344 clean-control samples correctly.

At slice 0, `K = 10`, and mask bit 32, the checked decoder labelled nine
wrong samples guaranteed at indices 101–109. The CRC filtered them. The
checked path returned unguaranteed at full reference 110 and delivered
again at 120, with further rejections in the recorded window. The basic
path delivered correctly from full reference 110 through the end of the
case. The receiver's acceptance and state policy therefore affects recovery
even when both paths receive the same references and source CRC.

At `K = 100` the longest gap was 99 samples. The largest single-case count
of wrong samples marked guaranteed was 85. The older wide campaign's
99-wrong-output witness was a separate test. This matrix has its own
declared injection positions and timing.

Changing the clean reference period from 100 to 10 increased compressed
payload plus source-CRC bytes by approximately 17–21% across the three
slices. This excludes transport framing, length metadata and channel coding.
The basic path recovered stably by the next full reference in all 54
injected cases. Its 9- and 99-sample maxima apply to these inputs and
faults. The CRC result and gap maxima do not establish a general integrity
or recovery guarantee.

Full references and resynchronization are established techniques. This
comparison applies them to an encoder-state fault with one pinned library
and one public telemetry record. [CCSDS 124.0-B-1](https://ccsds.org/Pubs/124x0b1.pdf) ·
[2024 resynchronization study](https://doi.org/10.1109/ACCESS.2024.3374227)

## Reproduce

Use the [repository prerequisites](../README.md#run) and run:

```sh
python tests/run_venus.py --check
```

The optional data download is about 13.6 MB. Fresh outputs go to
`runs/`. The check compares measurements and both CSV hashes with the
recorded run. [Summary](../evidence/venus-state/summary.json) ·
[Cases](../evidence/venus-state/cases.csv) · [Per-packet decisions](../evidence/venus-state/frames.csv)

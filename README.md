# CCSDS 124 Checked-Decoder Regression

An independent, fixed-wire ARM replay of a known checked-decoder accuracy counterexample, including no-loss controls.

## Run

Requirements: Python 3.12 and Arm GNU Toolchain (ARM_GCC or PATH). On Linux/macOS use `.venv/bin/python`.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python tests/run.py
```

`python tests/run.py --verify-only` checks the packaged file hashes without
rerunning the experiment. New runs go to ignored `runs/` directories (or
`outputs/` in the F Prime lab). Archived evidence is never used as an output target.

## Contents

- `src/`: independent C wrapper, linker script and Python ARM runner.
- `evidence/recorded/results.json`: original fixed-wire controls and counterexample traces.
- `tools/bootstrap.py`: checksum-pinned public upstream downloads.

## Encoder-state replay on Venus Express telemetry

The separate replay flips one bit of the C encoder's stored mask and compares
checked decoding with a basic decoding path on the same wire packets. The
source CRC filtered all wrong outputs marked guaranteed in the tested matrix.
At a ten-sample reference cadence, the longest observed gap was 19 samples
with checked decoding and nine with the basic path. [Experiment and evidence](docs/venus-state-replay.md)

```powershell
.venv/Scripts/python tests/run_venus.py --check
```

## Full references under a shared byte ceiling

The follow-up compares periodic references with an encoder that emits a
reference on a local mask CRC mismatch. It tests faults on both sides of the
CRC check and uses the same serialized byte ceiling for each alternative.
Before-check flips produced no gap. After-check flips escaped detection,
and the long fallback produced gaps up to 99 samples against 11 for the
best feasible periodic setting.
[Experiment and evidence](docs/reference-budget.md)

```powershell
.venv/Scripts/python tests/run_reference_budget.py --check
```

## Sender-side decode verification

A local decode compares each compressed payload with its source before
release and retries with a full reference on a mismatch. Under the same
serialized-byte ceiling as periodic K=12, the longest gap fell from 11
samples to zero across the tested fault cases. The linked fixture used
3,840 bytes more static RAM. [Experiment and evidence](docs/local-verify.md)

```powershell
.venv/Scripts/python tests/run_local_verify.py --check
```

## Sender work and decoder state copies

The follow-up profiles 2,784 packets across periodic transmission, the
original verifier and two versions that swap decoder buffers. It checks
the generated ARM instructions to explain the cost of the remaining
copy. [Experiment and evidence](docs/sender-work.md)

```powershell
.venv/Scripts/python tests/run_sender_work.py --check
```

## Recovery when a transmitted packet is lost

The loss replay drops specified packets after sender encoding while
keeping each sent stream and its byte budget identical to its intact-link
control. It compares periodic references with the sender-side verifier
when the receiver misses a repair packet or nearby data.
[Protocol and results](docs/reference-loss.md)

```powershell
.venv/Scripts/python tests/run_reference_loss.py --check
```

## Retuning periodic references for packet loss

The follow-up screens 17 periodic intervals against the original byte
ceilings and selects a common interval using the original erasure cases.
It pairs that result with the archived sender-verification policies.
[Protocol and results](docs/retuned-periodic.md)

```powershell
.venv/Scripts/python tests/run_retuned_periodic.py --check
```

## Matched-cadence decision recheck

The recheck tunes the verification interval on the original matrix and
tests it at previously unused fault positions. At K=11, the two policies
have identical gaps in all 96 erasure cases. Verification removes the
sender-fault gaps when the link delivers the repair. The paired sender
profile measures the instruction and stack cost of that trade-off.
[Phase comparison and resource measurements](docs/decision-recheck.md)

```powershell
.venv/Scripts/python tests/run_decision_recheck.py --check
.venv/Scripts/python tests/run_matched_sender_cost.py --check
```

## Scope

The original test reproduces a fixed counterexample across four builds and
eight reception configurations. The Venus Express experiments use separate
fault matrices. All execute in CPU emulation. The older extended POCKET+
report describes a different campaign.

This is a research implementation/archive, not flight-qualified software or a
claim of conference acceptance. Research and packaging used AI assistance.
The retained reports include negative findings and unresolved questions.

## Provenance and licensing

Original evidence was copied without overwriting its source directory. Portable
path changes are recorded in `provenance/patches/`; copied inputs and code have
SHA-256 provenance. `provenance/manifest.json` protects the curated files.
See `LICENSE.md` and `THIRD_PARTY_NOTICES.md`. GitHub publication is not performed
by any script in this repository.

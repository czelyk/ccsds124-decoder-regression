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

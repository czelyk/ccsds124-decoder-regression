# CCSDS 124 Checked-Decoder Regression

An independent, fixed-wire ARM replay of a known checked-decoder accuracy counterexample, including no-loss controls.

## Run

Requirements: Python 3.12 and Arm GNU Toolchain (ARM_GCC or PATH). On Linux/macOS use .venv/bin/python..

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

## Scope

A passing test means the archived discrepancy was reproduced, not that the decoder was repaired. Four builds and eight reception configurations exercise one fixed counterexample. This is CPU emulation, not physical STM32 testing. The separate older extended POCKET+ report ZIP is not bundled or claimed reproduced.

This is a research implementation/archive, not flight-qualified software or a
claim of conference acceptance. Research and packaging used AI assistance.
The retained reports include negative findings and unresolved questions.

## Provenance and licensing

Original evidence was copied without overwriting its source directory. Portable
path changes are recorded in `provenance/patches/`; copied inputs and code have
SHA-256 provenance. `provenance/manifest.json` protects the curated files.
See `LICENSE.md` and `THIRD_PARTY_NOTICES.md`. GitHub publication is not performed
by any script in this repository.

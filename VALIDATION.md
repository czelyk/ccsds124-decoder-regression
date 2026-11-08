# Packaging validation — 22 October 2026

The 8 November follow-up executes the C codec and two receiver paths over
13,440 frame exchanges in Cortex-M4 emulation. The [Venus Express replay](docs/venus-state-replay.md)
describes the independent checksum checks and the recorded gap measurements.

**Executed successfully in the curated working copy:** 4 independent ARM builds, 8 reception configurations; all no-loss controls passed and the fixed known counterexample reproduced.

Unicorn CPU emulation. A green test reproduces a known discrepancy; it is not a decoder fix or a flight-reliability result.

Raw fresh outputs are retained in `evidence/packaging-20261022/`; earlier evidence
remains in `evidence/recorded/`. The `verification.json` file records the actual
test working directory and the file count at execution time. Later additions of
documentation/evidence change the final package file count, not those results.

Environment: Windows, Python 3.12.10; applicable tools were Arm GNU 15.2.1,
Unicorn 2.1.4, pyelftools 0.32, Renode 1.17.0, OpenJDK 21.0.10 and Go 1.27.3.
Only tools actually used by this project are prerequisites; see README.md.

Historical reports retain their original scope, decisions and local source paths.
Use the current README for execution. Historical paths are provenance, not runtime
dependencies. The clean Git copy and ZIP are checked again with `--verify-only`.
No physical testing, new scientific GO, conference acceptance or publication is
claimed by this packaging operation.

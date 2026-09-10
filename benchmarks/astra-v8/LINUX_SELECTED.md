# Final default TT+LMR: completed Linux compatibility check

[Run 34472928110](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34472928110)
completed successfully on pushed commit `046a92565c23c5352bac48bddc8379f924e5efed`.
The selected source from commit `74ebe2b` has SHA-256
`31128444d171cc2526c99ff13cb92da43ad89ada9d99d14ec4bd53a0cc4da221`.
It was independently compared byte for byte with the first Linux source: its
only change is the default `USE_LMR = False` to `True`. Score TT remains enabled.

All **86 tests passed** in 32.055 seconds; ruff and strict mypy passed. The isolated
package confirmed both switches actually enabled and the 16-counter search active.
Initialization took 23.629 seconds; real search completed depth 5 in 0.147 seconds,
returned legal `c2c4`, and added no JIT signature. It recorded 1,184 score-TT
cutoffs, 1,235 LMR reductions and 40 full-depth verification re-searches during
that request. The independent runner initialized in 24.033 seconds and passed
standard, en-passant and 1 ms fallback requests. Two packaging smoke games
finished without failure. They are not the predeclared fast/formal strength batch.

The actual ZIP contains only `agent.py` and LICENSE. Its extracted source was
independently checked against the final source above; ZIP SHA-256 is
`580adaba115debc80bee33f564035b1c9d60c4855b9ef203bc072c6cd95d5818`.
[Download artifact 10150547464](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34472928110/artifacts/10150547464),
then use `packages/v8/agent-31128444d171.zip` inside it. The artifact expires
2026-10-10 and its downloaded archive SHA-256 was verified as
`e035788338e0f5e0b231026534a6db5f605b30b46d7877661e5c92cd6241772b` before safe extraction.

The workflow also repeated the fixed-depth benchmark. All 168 functional rows
(moves, scores, nodes, complete depths and counters) were identical to the first
Linux run. This repeat is retained separately; timing samples are **not pooled or
selected** to improve the headline. The first completed run 34470325484 remains
the primary efficiency measurement. Secondary ratios are recorded in the JSON
for completeness, not substituted for the primary result.

**Formal games: 0, NOT RUN.** That step was explicitly skipped by the preflight
trigger. This result verifies the final package's ordinary Linux compatibility;
it does not establish same-clock playing strength or replace official-container
validation. Actual resources/dependency versions are in `linux-selected-environment.json`.
Raw logs, all repeated rows, ZIP and smoke PGNs stay in ignored
`artifacts/v8-search/linux-selected/`; the public aggregate is
`linux-selected-summary.json`. The first preflight evidence remains unchanged.

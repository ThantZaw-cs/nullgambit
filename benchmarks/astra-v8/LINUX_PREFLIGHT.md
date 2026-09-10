# Completed Linux preflight — search efficiency, not strength acceptance

[Run 34470325484](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34470325484)
completed successfully on commit `28beb38b524b37100e5ae1089422a295b8460094`.
The checked candidate is
`43ce05eafcd9f76d75f0f5bf3fb675912d314311478329157c8656632b7480b8`;
frozen v7 is `aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d`.
The package default is TT on / LMR off. No strength configuration has been selected
by this compatibility run. The earlier defective `20cf…fa8b` quality batch is not
included in these results.

All **86 tests passed** in 28.846 seconds; ruff and strict mypy passed. The host was
Ubuntu 24.04, Linux 6.17 Azure x86_64, Python 3.12.3, Intel Xeon Platinum 8573C,
CPU affinity `[0]`, numerical library threads 1, and 2 GiB address-space limits for
performance and package processes. Dependencies were installed from the unchanged
lock. This is ordinary Linux compatibility, not the official competition container.

The predeclared 14 seen ordinary/Slav regressions completed all **168/168** rows:
four configurations, three repeats, iterative D1–5. Each case/configuration was
warmed first; measurement order rotated. Allocation, history seeding and all
completed search iterations were timed. Imports/compilation were separate:
v7 14.769 seconds, candidate 15.853 seconds. The whole stage took 183.580 seconds.

| Configuration | Geometric latency vs v7 | Total nodes | Worst position median ratio | Score-TT cutoffs | LMR reductions / verification re-searches |
| --- | ---: | ---: | ---: | ---: | ---: |
| v7 | 1.00000 | 4,994,679 | 1.00000 | 0 | 0 / 0 |
| TT | 0.92893 | 4,566,813 | 1.00158 | 14,973 | 0 / 0 |
| LMR | 0.58228 | 3,000,726 | 0.95229 | 0 | 48,399 / 96 |
| Both | 0.52699 | 2,697,513 | 0.92508 | 35,127 | 48,399 / 96 |

TT preserved all **210 paired iteration scores** and all 42 final moves; its
hit/cutoff rates were 27.86% / 4.55% of 328,977 probes. The combined rates were
28.87% / 15.77% of 222,762 probes. TT had 4/42 individually slower measurements;
worst was +3.64% (`slav11:36`, repeat 0). Median v7 relative MAD across positions
was 0.84%. LMR and both had no slower individual pairs in this sample, but each
changed the final score in 18/42 and move in 21/42 measurements. These selective
search differences require external move-quality and match validation; fewer
nodes or faster fixed-depth work does not establish increased playing strength.

The actual ZIP was independently hash-checked and contains only `agent.py` and
LICENSE. Isolated import took 18.008 seconds; actual search completed depth 5 in
0.146 seconds, returned legal `g1f3`, and added no JIT signature. The independent
runner passed standard, en-passant and 1 ms fallback requests. Both package smoke
games completed without process/protocol failure. These are not strength games.
ZIP SHA-256: `44cdc5f387b60998128f2972024f9007994ff6cc46c80a9a705d0cbec2f55b2e`.

**Formal 20-game control: NOT RUN.** The formal step was explicitly skipped by the
preflight-only trigger; package smokes do not replace the declared fast/formal
batches. No match batch was rerun. Independent quality and playing-strength gates
remain the responsibility of the complete v8 review.

The [complete artifact](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34470325484/artifacts/10149481954)
expires 2026-10-10. Its archive SHA-256 was independently verified as
`ba7db879d7c1566d7ddef7a29b46c5e686eb3a5b3b752d70fd56051067c9bacc` before safe extraction.
Public aggregate evidence is in `linux-preflight-summary.json`,
`linux-preflight-environment.json`, and `linux-package-summary.json`.
Raw CI logs, every performance row, ZIP and smoke PGNs are retained locally under
ignored `artifacts/v8-search/linux-preflight/`; no teacher or online originals were
added to this public evidence.

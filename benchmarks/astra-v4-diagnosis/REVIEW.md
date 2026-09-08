# v4 post-upload regression diagnosis — 2026-09-08

Started 09:15:20 UTC with a clean `astra-v4` checkout at
`b32c1c574d21f97d833e102c2176670f1a6aa82a`. The time budget is approximately two
hours. No engine algorithm, evaluation, time policy, referee or competition
submission is changed. All original online PGN/LOG/CSV/ZIP files remain private.

## Frozen identities and version attribution

- v4: `baselines/online_v4/agent.py`, byte-identical to the existing prototype,
  SHA-256 `7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4`.
- v3: `baselines/online_v3/agent.py`, still byte-identical to the supplied v3 ZIP,
  SHA-256 `b08ab63e695f971e6322353eb5bba4657c91e901ac9b0b6fb9a326f1def56297`.
- Root legacy `agent.py` is not used in the comparison. Both frozen sources and
  the prototype are checked by hash; runtime telemetry never changes their files.

| Record | UTC timestamp | Attribution |
| --- | --- | --- |
| Round 60, QueenC4 | 2026-09-07 21:27:37 finished | Definitely pre-v4; exact earlier build unidentified |
| v4 validation | 2026-09-08 08:10:42 building; 08:12:49 valid | Upload passed validation, not a rated-game build identity |
| Round 61, lefischer | 2026-09-08 08:26:44 finished | Unknown build |
| Round 62, Brokefish | 2026-09-08 08:45:53 finished | Unknown build |

Match LOG timestamps explicitly say UTC; CSV timestamps carry `+00:00`. PGN
`Date` is date-only and does not supply a time zone or start time. The validation
log has `HH:MM:SSZ` only: its calendar date is inferred from the collection date
and supplied upload context, not encoded in that log. Initialization times and
finishing after validation do not identify the builds used in rounds 61/62.
`tools.online_review` now leaves its timing-based version hint unknown as well.
Historical timing cohorts are not counted as verified v3/v4 win rates.

## Replay and actual-clock probes on Mac

All moves are replayed from each actual starting FEN, including both sides and
all observed repetition history. Round 60 has 102 plies / 51 own moves; round 61
has 104 / 52; round 62 has 87 / 43. All reach the recorded checkmate. There is no
illegal move, malformed reply, stderr failure or flag in the supplied records.
Own remaining time at the end is 42.958 / 42.238 / 49.640 s respectively.
The earlier prose claiming 103 plies for round 60 was a documentation miscount;
the original private replay JSON already said 102.

The real frozen `get_move` is called with the PGN-derived remaining clock and
the complete observed history. Both versions run sequentially in the same Mac
process, numeric thread limits set to one, alternating version order. This is
a counterfactual comparison on one Mac, not a recreation of an unknown online
machine's speed or an assertion about its deployed version.

- Initial scan: 67 own decisions in rounds 61/62 through fullmove 40, 134 calls.
  Optional outer-call telemetry records completed iterations without replacing
  the search. Average completed depths: round 61 v3 5.54 / v4 6.40; round 62
  v3 6.59 / v4 7.16. Greater depth alone is not a strength conclusion.
- Every observed v3/v4 move disagreement plus four shared decisions is repeated
  three times per version without telemetry: 19 positions, 114 calls.
- Four pre-v4 round-60 positions are checked three times per version: 24 calls.
- The timing-sensitive round-62 move 38 gets six further predeclared repeats
  per version: 12 calls. All outcomes of all repeats are retained.
- Total: **284 real-entry calls**, all legal, within their supplied clocks, and
  with matching observed history. Their call times are approximately 1.69–2.51 s.
  Initial scan clocks were floored from floating-point PGN values (occasionally
  1 ms lower); subsequent repeats use the nearest reported millisecond. Neither
  restores unavailable sub-millisecond online clock precision. Both versions
  always receive the same input clock.

For round 62 move 38, the nine uninstrumented v3 repetitions produce Bd3 at
depth 8 twice and Kf4 at depth 9 seven times; all nine v4 repetitions produce Kf4
at depth 9. Thus the first v3/v4 difference is partly a completed-depth boundary,
not evidence that v3 cannot find the move. Other measured differences can also
be equal-score alternatives rather than improvements or regressions.

## Earliest supported review windows

The following scores use our own evaluator, not an external engine or an
absolute chess answer. Extra 15/30/45 s search caps are diagnostic only and never
change the deployed clock policy. Scores from aborted searches are null.

| Position | Evidence | Interpretation |
| --- | --- | --- |
| 61 / 24...Rb6 | Depth 7: Rb6 -83 cp, Rbc8 -2 cp, independently identical in v3/v4 | Earliest substantial measured concern; precedes loss of a5 and a dangerous distant passer |
| 61 / 35...Nc8 | Depth 9: Nc8 -318, Nc6 -199, independently identical in v3/v4 | Later, clearer promotion-defense horizon concern |
| 62 / 23.f4 | Remains best at depth 7, +59 | The visible exchange sequence alone is insufficient to call this a blunder |
| 62 / 29.exd5 | Depth 7 exd5 +62 vs cxd5 +61; depth 10 exd5 +3 vs cxd5 +51 | Earliest measured structural review window, but modest and depth-sensitive |
| 62 / 38.Bd3 | Depth 10 Bd3 -332, Kf4 -182, Ke4 -174 | Later, clearer rook/passed-pawn race concern; the position is already unfavorable |

Earlier tested deviations are small: e.g. 61/6 cxd4 is only 3 cp below the
depth-7 best despite a different depth-6 choice; 61/19 f5 differs by 12 cp and
61/23 Qa3 by 18 cp. This does not prove all earlier play was optimal. It explains
why the more concrete windows above are prioritized instead of the final mate.

At actual clocks, three uninstrumented repeats each give v3 Rb6/d5 versus v4
Rbc8/d6 at 61/24, and v3 Nc8/d6 versus v4 Nc6/d8 at 61/35. These positions do not
support a v4-specific regression. They also cannot identify the online build.

| Decision | Input clock | v3: move / completed depth / elapsed range | v4: move / completed depth / elapsed range |
| --- | --- | --- | --- |
| 61/24 | 83.955 s | Rb6 / 5 / 2.400–2.402 s | Rbc8 / 6 / 2.398–2.402 s |
| 61/35 | 65.774 s | Nc8 / 6 / 1.879–1.881 s | Nc6 / 8 / 1.879–1.881 s |
| 62/29 | 80.205 s | exd5 / 7 / 2.292–2.294 s | cxd5 / 8 / 2.291–2.293 s |
| 62/38, first three repeats | 65.785 s | Bd3 / 8 twice; Kf4 / 9 once / 1.879–1.881 s | Kf4 / 9 / 1.880–1.881 s |

Ranges are rounded outward to milliseconds. The subsequent six repetitions of
62/38 also use 65.785 s and are included in the nine-repeat conclusion above.
All 22 predeclared common-depth branch calls are retained: 21 complete, one
times out. Every branch completed by both versions gives exactly the same score.
The exception is 61/39 Ra4 at depth 10: v3 exhausts its 45 s diagnostic cap and
has no score; v4 completes at -537 cp. Kxe8 is -750 cp in both. The missing v3
score is not filled from v4 or selectively retried. The formal control is still
required before a version recommendation.

An AST audit confirms v3/v4 have identical `get_move`, time allocation, history
restoration, evaluator, structure evaluator, quiescence, draw-history check,
make/unmake and history seeding. The only engine differences are the previously
frozen quiet-move ordering changes. The shared passer/promotion horizon is a
supported development hypothesis; an evaluation bias is plausible but not yet
isolated from search. No new engine defect has been established by these probes.

## Predeclared Linux formal control

`plan.json` was fixed before launch, SHA-256
`e12b549b44039d70594a85c42327156abec7461e5da6217ef466d4877f5ac9e4`.
It contains ten distinct, previously used development openings, explicitly a
**regression set**, not unseen validation. Each is played with swapped colors:
20 games, 120 s + 0.5 s per side, sequentially on one Linux x86_64 runner with
one-CPU affinity and identical frozen sources/dependencies/resources.

[Formal run 34209500665](https://github.com/ThantZaw-cs/nullgambit/actions/runs/34209500665)
tests commit `5fcca3db1f594c872dad21ab5872d05f4df194a9`. It has a predeclared 95-minute
execution cap, never a score-based stopping rule. No losses are retried. The
unchanged local referee uses its 60 s init limit and raw 600-ply material
adjudication; cap scores are not rewritten and any such endings must be reported
separately. This is a host control, not the official full competition container;
no special 2 GB quota, network isolation or read-only filesystem is imposed.
The raw `environment.json` reuses the release helper: its generic prose mentions
300 plies and smoke games. Those two descriptions do not apply to this run;
the predeclared plan and executed call use 600 plies and 120+0.5. Raw environment
metadata is retained unchanged, with this correction stated explicitly.

The separate ordinary CI run passed all 56 tests, ruff and strict mypy. Its
short smoke games are not included in or substituted for this formal batch.
After adding the local diagnosis/audit tools, the Mac rerun also passes all
56 tests (12.097 s test body), ruff and strict mypy (29 checked source files).
Formal results are pending completion; no result or recommendation is inferred
from the fact that the workflow is running.

## Private evidence and reproduction

Private intake, original-file manifest, clock scans/repeats, history fingerprints,
completed-depth traces and cross-scores are saved under the ignored directory
`data/online/2026-09-08/derived/v4-diagnosis/`. No raw online files are sent to CI.
Public scripts: `tools.diagnose_online_v4`, `tools.diagnose_v4_depth`,
`tools.formal_v4_control`, `tools.summarize_v4_control`. The first two require
the local private inputs; normal CI tests and the formal control do not.

For private reproduction, set `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
`NUMBA_NUM_THREADS` and `MKL_NUM_THREADS` to `1`, then use the locked Python
environment. Each output name must be new, to prevent overwriting evidence:

```sh
python -m tools.diagnose_online_v4 --rounds 61 62 --last-fullmove 40 --telemetry --out PRIVATE/scan-new.json
python -m tools.diagnose_online_v4 --select 61:24 61:35 62:29 62:38 --repeats 3 --out PRIVATE/repeats-new.json
python -m tools.diagnose_v4_depth --scan PRIVATE/clock-scan.json --choice-plan PRIVATE/cross-score-plan.json --versions v3 v4 --out PRIVATE/cross-new.json
python -m tools.summarize_v4_control benchmarks/astra-v4-diagnosis/linux-formal
```

`PRIVATE` denotes the ignored local diagnosis directory, never a public fixture.
The common-depth CLI reproduces the same branch evaluator and predeclared plan
used by the recorded one-off cross-check; that later CLI addition does not imply
the 22 measurements were rerun. The full 19-position repeat selection is retained
privately in `repeat-selection.json`; the four-position command above is only a
focused reproduction example, not the complete original repeat batch.

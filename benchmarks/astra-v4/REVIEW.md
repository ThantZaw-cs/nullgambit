# Astra v4: online evidence and a bounded ordering experiment

Release review update: the source described here remains frozen. The separate
`RELEASE.md` records Draft PR #2 and actual Linux compatibility validation. Its
two short Linux smoke games were both losses by checkmate, with no program
failure; this does not extend or replace the Mac strength evidence below.

Started 2026-09-08 02:04 UTC on `astra-v4`, commit
`639fc47922b49d363962a5c0a73a7b4e69192f49`. The only initial untracked work was
`data/`. Root agent and `harness/` are unchanged. No push, merge, upload, external
engine, pretrained weights, paid service, or competition interaction was used.

## Identity and provenance

The ZIP's `agent.py` matched the prototype byte for byte, SHA-256
`b08ab63e695f971e6322353eb5bba4657c91e901ac9b0b6fb9a326f1def56297`.
It is now the main opponent in `baselines/online_v3`. The root agent remains the
older SHA-256 `887d8ca093d429d305cac98272d28447611bdcf07ac25ab5174c41ca6b6018f5`.
Original online files and derived move logs remain under ignored `data/online/`.

38 CSV rows cover rounds 23–60, with 38 unique round keys. The initial timing
cohorts are 31 likely legacy games (+13 =1 -14, three voids) and seven likely
Numba games, rounds 54–60 (+4 =1 -2). These are **inferred cohorts**, not verified
v3 build statistics: PGNs/LOGs do not include a per-game submission ID/hash.
The supplied upload validation log is named for the v3 ZIP hash, but gives only
time-of-day timestamps. Exact per-game version remains `unknown` in the import.

`tools.online_review` pairs logs by round, opponent and actual starting FEN,
uses match ID for deduplication when available, and rejects conflicting exports.
It checks every legal move, SAN, own-move index, rounded log time and PGN clock.
It replays from the supplied FEN, retaining both sides' move stacks; no opening
history before that FEN is invented. Full output is private at
`data/online/2026-09-08/derived/intake.json`.

## Independent review, in requested order

Scores below are from our own unchanged evaluator at completed search depths.
They are diagnostic evidence, not authoritative chess evaluations or proof that
an alternative wins. Online logs contain no depths, nodes or evaluations.

### Round 58, Alpha Knights

97 legal plies from the Dragon FEN; 48 NullGambit moves. Checkmate and clocks
match the supplied records. The final clock is 45.283 s, so this was not a flag.
The first useful review window is 14–18, well before the final mate: `14.Rad1
Rb8 15.Rb1 Qa5 16.f3 Be6 17.g4 Rb4 18.a3 Qb6+ 19.Kh1 Rxb2`.
This spends rook tempi and permits pressure on b2 while expanding the king's pawns.

At 17.g4, 103.964 s remained before the move, and the log records about 2.5 s
used. In the v3 diagnostic, depth 4 chooses g4 (+69 cp), depth 5 chooses a4
(+61 cp). The depth-5 iteration alone needs 394,298 nodes after 19,862 at depth
4. At common depth 6, a4 scores +57 and the recorded g4 scores -45. This is a
specific search-horizon concern with a 102 cp gap in our evaluator. It is not a
claim of a forced win or proof of the actual online depth. By contrast, 16.f3
returns as best at depth 6, and 18.a3 also remains best; the shallow scan alone
would have been insufficient to call these errors. Earliest small concern at
15.Rb1 is only 8 cp at depth 6 and is not treated as a proven mistake.

### Round 60, QueenC4

103 legal plies from the Italian FEN; 51 NullGambit moves. Checkmate and clocks
match; 42.958 s remains at the end. Inspect the opening's early `7...Ng4` and
`8...Be6`, but common-depth gaps are only 7 and 6 cp: there is no good evidence
to label either the decisive mistake. Later review windows are `23...Nc4`,
`29...b5` and `34...Rac8`, whose depth-6 gaps are 51, 30 and 31 cp respectively.

`36...h5` (65.775 s before the move, about 1.9 s used) permits the concrete
checking sequence `37.Rg6+ Kf7 38.Rf6+ Qxf6 39.Nxf6 Kxf6`, trading Black's queen
for rook and knight. At depth 6 h5 scores -822, versus -731 for Rd2: the position
was already substantially worse before this exchange. It is therefore a later
tactical symptom, not an explanation of the entire loss. Slow deterioration
could include evaluation bias; this run does not isolate or alter that factor.

### Round 54, AlphaGambit

101 legal plies from the Spanish FEN; 50 NullGambit moves. The final position
really permits the referee's threefold claim. History is preserved throughout.
The earlier critical decision is `27.h3` with 85.901 s remaining, following
`25...Nfxd5 26.exd5 Nxd5`. Black then plays `...Nc3`, attacks Qb1 and Ba2,
and after the queen moves takes both bishops on a2 and c1. Depth 4 chooses h3;
depth 6 chooses Nf1 (-145), with recorded h3 at -309. The 164 cp difference
supports reviewing the horizon before changing draw handling.

At move 59, Qe8+ scores zero with the real repetition history. The ending is a
successful perpetual-check escape from an otherwise difficult position, not
evidence of a repetition implementation bug. At move 56 our limited search
still scores -503; that horizon is explicitly insufficient to evaluate the
entire eventual perpetual sequence.

One referee detail differs: python-chess `claim_draw=True` can already claim the
repetition immediately before `59...Kh7`, while the online PGN includes that
move and reaches the actual third occurrence. Both give a draw. This one-ply
difference is recorded in the private repetition audit, not called an agent bug;
the local referee is unchanged.

### Failure categories

- Search insufficiency: supported as a development hypothesis by depth-dependent
  decisions and large next-depth costs, especially 58/17 and 54/27.
- Evaluation bias: possible (king safety, activity and static material tradeoffs),
  not separated from search here. No evaluation coefficient was changed.
- Time allocation: confirmed conservative 2.5 s cap and unused time in losses;
  harmful allocation is unproven without a controlled clock-policy experiment.
- Implementation faults: no illegal move, malformed reply, crash, flag or history
  mismatch found in these three logs or replay. Draws are not classified as faults.

## The one engine change

Candidate SHA-256:
`7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4`.

Adds bounded quiet-move history ordering to the compiled search: a quiet beta
cutoff receives a depth-squared bonus, separated by side/from/to and capped at
16,384. Tactical moves keep higher priority. A valid TT move is tried first;
without it, the first move is now ordered too. The scratch table is allocated
per root search, is 65,536 bytes, and never stores a score or a draw result.
Evaluation, quiescence, draw semantics, time policy and public contract are
unchanged. This extends the existing engine; it is not a rewrite.

12 declared development positions from rounds 58/60 were measured sequentially
with alternating engine order. At depth 5 all 12 scores agree with frozen v3.
Median candidate/baseline nodes = 0.379; wall time = 0.361. Average complete
depth at 0.1 / 0.5 / 2.5 s is 3.75 / 4.75 / 5.83, versus 3.58 / 4.25 / 5.08.
Raw measurements and per-iteration scores are in `development-search.json`.

The review games are development data. Six new legal opening positions were
written to `validation-openings.json` before editing the candidate; none are in
the old development/confirmation/holdout suites. Formal validation uses all six
with swapped colors after a 20-game fast screen. No candidate tuning is allowed
after formal validation starts. The old holdout has been used historically and
is not claimed as unseen.

## Environment and limits

Mac arm64, Python 3.12.13, chess 1.11.2, numpy 2.5.2, numba 0.67.0. Minimal
dependencies were installed in `.venv` without changing `uv.lock` or requesting
unused torch/onnx packages. A sandbox DNS failure was resolved by one authorized
network escalation; no repeated failed dependency attempts were made.

The live canonical contract and rules were fetched and saved here. They specify
90 s init, suspended opponents, and a 600-ply draw; repository quick-reference
values differ. The harness remains unchanged (60 s init and old cap behavior).
The existing comparison tool requests 600 plies and reports cap draws; any cap
or harness discrepancy must be identified in the final results. No observed
test result should be substituted for an upload validation decision.

Matches are serial, independent fresh processes, same start FEN and clocks,
swapped colors, with Numba/OpenBLAS/OMP thread counts set to one. Mac scheduling
does not reproduce Linux one-core/2 GB container isolation. Docker/Podman/Lima
are absent, so no new Linux validation is claimed. The supplied Linux v3 smoke
log reports `valid`; it does not validate this candidate. Fresh Mac candidate
import was 5.616 s. `/usr/bin/time -l` could not read a restricted sysctl, so it
does not provide a trustworthy memory measurement.

## Match results and final recommendation

Fast screen completed all 20 games (10 opening pairs), 10 s + 0.1 s:
**+7 =8 -5, 55%, failures 0, voids 0**. Seven threefold draws, one insufficient
material draw and 12 checkmates; no cap adjudication. All 20 PGNs replay legally.
Pair-level exploratory bootstrap 95% interval: 40%–67.5%. Duration 636.18 s.
This is a modest positive screening result, not a confirmed strength increase.

The complete 53-test suite (including the online 27.h3 fork regression), ruff and
strict mypy pass. The registered formal batch completed all 12 games (six fresh
opening pairs), 120 s + 0.5 s: **+6 =6 -0, 75%, failures 0, voids 0**. Six
checkmates and six threefold draws; no cap adjudication. All PGNs replay legally.
Duration 2,555.85 s (42 min 36 s); source hash is identical to the fast screen.

Pair scores are `1, 1, 0.5, 0.75, 0.5, 0.75`. Exploratory bootstrap 95% interval:
58.3%–91.7%. Four pairs favor the candidate, two tie; the descriptive two-sided
sign test is p=0.125. With only six openings, the bootstrap interval must not be
treated as proof of a general improvement. Fast-screen sign-test p=0.453125.
Neither batch establishes Elo, and their differing time controls are not pooled.
These six validation openings are now used data for future work.

**Retain this candidate for the next validation stage.** Reduced search work at
unchanged depth scores and favorable independent match results support keeping
the change, while Linux validation and a larger fresh opening sample remain
necessary. There was no tuning after screening and no early stopping.

The local ZIP `artifacts/astra-v4-history-7f451006.zip` contains root `agent.py`
and `LICENSE` only. ZIP SHA-256 is
`7d9991b8436d1b7b2a1c4e267cd0bcd0c1fc319af8313809f38e54c49bb9ea95`.
The extracted agent matches the tested candidate byte for byte. A fresh runner
initialized in 6.042 s and returned three legal moves within the supplied clocks,
with empty stderr. The 1 ms probe returned in 0.094 ms. POSIX child resource
accounting, which works despite the restricted sysctl, measured peak runner RSS
of 289,849,344 bytes (276.4 MiB) on Mac; it is not a Linux quota test.

Still missing: an online winning-game PGN/LOG for the requested spot-check and
per-game submission attribution. The three supplied PGNs cover two losses and
one draw. These gaps are not filled with inferred wins or historical aggregate
scores. All private originals remain ignored and local. No push, merge, upload,
paid service, third-party engine or pretrained weights were used.

Reproduction, using the already prepared minimal `.venv`:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/python -m tools.online_review
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m tools.history_experiment
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m tools.online_probe
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m tools.compare --agent prototypes/numba_kernel --opponent baselines/online_v3 --pairs 10 --suite development --base-ms 10000 --increment-ms 100 --out benchmarks/astra-v4/fast-screen
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m tools.compare --agent prototypes/numba_kernel --opponent baselines/online_v3 --pairs 6 --positions-file benchmarks/astra-v4/validation-openings.json --base-ms 120000 --increment-ms 500 --out benchmarks/astra-v4/formal-validation
.venv/bin/python -m tools.summarize_matches benchmarks/astra-v4/fast-screen.json
.venv/bin/python -m tools.summarize_matches benchmarks/astra-v4/formal-validation.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python -m tools.check_package --archive artifacts/astra-v4-history-7f451006.zip --source prototypes/numba_kernel/agent.py --out benchmarks/astra-v4/package-runtime.json
```

Use a new output basename when rerunning match batches to preserve these results.

# Classical search improvements

This page records version two, now preserved in `baselines/classical_v2`. The next
evaluation experiment is documented in [POSITIONAL.md](POSITIONAL.md).

Measured locally on Windows with Python 3.12 on 5 September 2026. The opponent is our
saved first engine in `baselines/classical_v1`, rather than the much weaker starter baselines.

## What changed

- The numerical evaluator accepts eight bitboards directly and is compiled by Numba during
  import. It uses the same material and piece-square scores as the first engine. An explicit
  unsigned signature handles squares in the high half of the bitboard. Disk caching and
  parallel compilation are not enabled.
- Quiescence generates captures and promotions directly. It checks for stalemate before
  evaluating a position, and still searches every legal evasion when in check.
- A transposition table retains depth, score, bound, and best move across turns. It has a
  20,000-entry limit. Score keys include the fifty-move clock and exact repetition counts,
  preventing reuse across incompatible draw histories. Mate scores are normalized for ply.
- Principal-variation search probes alternatives with a narrow window before doing a full
  search. Checks extend the horizon. Late quiet moves at non-PV nodes can be reduced one ply;
  an improvement must be confirmed at full depth.
- The move budget is unchanged from the saved engine, so the comparison gives both versions
  the same time-allocation policy.

The initial profile showed that generating and filtering all legal moves in quiescence was
the largest expense. Moving evaluation into Numba and avoiding unnecessary move generation
addressed those measured costs. Move generation and recursive search still use Python.

## Measurements

| Measurement | Previous engine | Current engine |
|---|---:|---:|
| Median searched nodes per second over ten positions | 11,439 | 24,790 |
| Median throughput ratio | 1.00 | 2.17 |
| Completed nominal depth at 0.5 seconds per position | 2–3 | 2–3 |

The new search completed depth 3 in four positions where the old search stopped at depth 2.
Extensions and reductions make nominal depths imperfect comparisons; throughput alone also
does not establish playing strength. Raw records are in
[`search-performance.json`](../benchmarks/search-performance.json).

Each match batch uses ten opening positions, one game with each colour, at 5 seconds plus
0.1 seconds per move. The first batch used the intermediate engine saved in
`baselines/search_speed`. The second used the current `agent.py`.

| Version against classical_v1 | Wins | Draws | Losses | Score | Runtime failures |
|---|---:|---:|---:|---:|---:|
| Speed and cache changes | 10 | 3 | 7 | 57.5% | 0 |
| With extensions and reductions | 13 | 1 | 6 | 67.5% | 0 |

The final report is [`classical-v2.json`](../benchmarks/classical-v2.json), with the matching
replays in `benchmarks/classical-v2.pgn`. Reports include source hashes to identify the version
tested. The intermediate report is `benchmarks/search-speed.json`.

These are small development samples using the same opening pool, not an independent strength
estimate. They do not establish an Elo rating or predict tournament placement. Longer clocks,
unseen openings, and stronger opponents remain useful follow-up measurements.

One remaining weakness is visible in the first Ruy Lopez replay: White advances its kingside
pawns and is eventually mated on g2 after Black's queen and rook penetrate. The evaluator still
lacks explicit pawn-shield and king-attack terms; faster search does not eliminate that gap.

## Validation and reproduction

The 23 regression tests cover tactics, special moves, quiet underpromotion, timeout unwinding,
unsigned bitboards, evaluator agreement, cached mate distances, repetition context, and cache
capacity. Ruff and strict mypy include the agent, harness, benchmark tools, and tests. The gate
also completed two games against random without a failure.

The packaged ZIP was extracted and run in a fresh agent process through the actual runner.
Initialization, including Numba compilation, took 1.16 seconds locally. All three protocol
checks returned legal moves, with no stderr output; see
[`packaged-runtime.json`](../benchmarks/packaged-runtime.json). The ZIP and both final benchmark
reports were checked against the same agent source hash.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m tools.benchmark
.\.venv\Scripts\python.exe -m tools.compare --out benchmarks/new-run
.\.venv\Scripts\python.exe -m harness.package
```

Run timed measurements without other CPU-heavy work. PGNs are ignored by Git; local runs save
them alongside the JSON reports. Neither benchmarks nor baseline copies enter the submission ZIP.

The harness is unchanged. `tools.compare` requests a 600-ply cap and scores cap outcomes as draws
when recording its results, matching the [live documentation](https://aichessathon.com/docs).
The older harness itself still adjudicates material at its configured cap. None of the recorded
games reached the cap. Platform upload validation remains a separate check.

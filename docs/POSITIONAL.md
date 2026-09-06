# Positional evaluation experiment

This iteration compares the candidate in `agent.py` with the frozen second engine in
`baselines/classical_v2`. Search, move ordering, and the clock policy are the same in both.
Only the evaluation changes. This is a handcrafted evaluator, with no trained model or weights.

## Evaluation changes

The candidate adds phase-scaled terms for:

- Pawn cover on the king's file and adjacent files, with a smaller bonus for cover two ranks
  ahead and a penalty for exposed files when enemy rooks or queens remain.
- Weighted enemy attacks into the squares around the king. Pressure from several pieces grows
  quadratically up to a cap. Its value decreases when the attacking side has no queen.
- Doubled and isolated pawns, pawn support, and passed pawns with larger endgame bonuses.
- Rooks on open and semi-open files.

The king terms fade out as non-pawn material disappears. They therefore do not discourage
an active king in a pawn endgame. Attack maps are pseudo-attacks used only for evaluation;
`python-chess` still generates every legal move in the search.

All added numerical work compiles at import using Numba, with unsigned bitboards and no disk
cache. The added evaluation uses the same API and requires no files beside `agent.py`.

## Checks and comparison design

Thirty-two tests cover the previous engine's search regressions and the new evaluation properties.
The compiled attack maps are compared against `python-chess` on 250 generated legal positions,
including blockers and high-bit squares. Tests check colour symmetry, pawn-shield preference,
passed pawns, rook files, king activity in pawn endgames, and board corners.

A passed-pawn test caught a reversed colour index during implementation; it was corrected
before playing either match batch. The base evaluator still agrees with the first version,
while the full evaluator deliberately adds the new positional terms.

The development batch plays the first six old opening positions with both colours at
5 seconds plus 0.1 seconds per move. It finished at **4 wins, 5 draws, and 3 losses (54.2%)**,
with no runtime failures. This is weak evidence by itself.

Ten different opening positions were defined before the new evaluation was implemented.
They are reserved for the holdout batch at **10 seconds plus 0.2 seconds per move**, with
both colours. The candidate is frozen throughout that batch; the comparison tool rejects
source changes between games. It writes source hashes and every result to JSON, and saves
replays in a PGN beside the report.

The holdout finished at **7 wins, 8 draws, and 5 losses (55%)**, with no runtime failures.
Because that margin is small, a further confirmation batch uses ten additional opening
positions at **15 seconds plus 0.2 seconds per move**. No evaluation coefficients or search
code were changed after seeing the holdout results.

Reports:

- `benchmarks/positional-development.json` and `.pgn`: development games.
- `benchmarks/positional-holdout.json` and `.pgn`: reserved positions at the longer clock.
- `benchmarks/positional-confirmation.json` and `.pgn`: additional positions with a frozen candidate.
- `benchmarks/positional-performance.json`: equal-time throughput against version two.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m tools.benchmark --reference v2
.\.venv\Scripts\python.exe -m tools.compare --opponent baselines/classical_v2 --suite holdout --base-ms 10000 --increment-ms 200 --out benchmarks/new-holdout
```

The Catalan loss in the holdout shows a remaining limitation: Black's passed b-pawn reached
b2, and Black later won a pawn race and promoted. The evaluator does not yet model blockades
or king distance to promotion squares explicitly.

Each batch is small, so its score should be treated as an initial comparison, not an Elo
estimate. These opening positions cease to be an untouched holdout if their results are used
to tune the next candidate. Tournament results and additional opponents remain useful evidence.

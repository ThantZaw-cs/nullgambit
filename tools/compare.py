"""Play both colours from each opening using the unchanged match harness."""

import argparse
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import chess.pgn

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.sandbox import local
from tools.positions import positions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", type=Path, default=Path("."))
    parser.add_argument("--opponent", type=Path, default=Path("baselines/classical_v2"))
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--positions-file", type=Path)
    parser.add_argument(
        "--suite", choices=("development", "holdout", "confirmation"), default="development"
    )
    parser.add_argument("--base-ms", type=int, default=5000)
    parser.add_argument("--increment-ms", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/latest-comparison"))
    args = parser.parse_args()
    starts = positions(args.suite)
    if args.positions_file is not None:
        supplied = json.loads(args.positions_file.read_text())
        starts = [(str(row["name"]), str(row["fen"])) for row in supplied]
        if len({fen for _, fen in starts}) != len(starts):
            parser.error("--positions-file contains duplicate FENs")
        if any(not chess.Board(fen).is_valid() for _, fen in starts):
            parser.error("--positions-file contains an invalid FEN")
    if not 1 <= args.pairs <= len(starts):
        parser.error(f"--pairs must be between 1 and {len(starts)}")
    if args.base_ms <= 0 or args.increment_ms < 0:
        parser.error("clocks must have a positive base and nonnegative increment")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    agent_hash = hashlib.sha256((args.agent / "agent.py").read_bytes()).hexdigest()
    opponent_hash = hashlib.sha256((args.opponent / "agent.py").read_bytes()).hexdigest()
    records: list[dict[str, object]] = []
    pgns: list[str] = []
    wins = draws = losses = failures = 0
    for name, fen in starts[: args.pairs]:
        for as_white in (True, False):
            if (
                hashlib.sha256((args.agent / "agent.py").read_bytes()).hexdigest() != agent_hash
                or hashlib.sha256((args.opponent / "agent.py").read_bytes()).hexdigest()
                != opponent_hash
            ):
                raise SystemExit(
                    "Agent source changed during the match batch; results are incomplete."
                )
            white, black = (args.agent, args.opponent) if as_white else (args.opponent, args.agent)
            outcome = play_match(
                local(white),
                local(black),
                args.base_ms,
                args.increment_ms,
                start_fen=fen,
                ply_cap=600,
            )
            # The old local harness adjudicates material at its cap. For these
            # comparisons only, count cap outcomes as draws, as the live docs say.
            result = "draw" if outcome.termination == "adjudication" else outcome.result
            termination = (
                "ply_cap" if outcome.termination == "adjudication" else outcome.termination
            )
            if result in ("draw", "void"):
                draws += 1
                score = 0.5
            elif (result == "white") == as_white:
                wins += 1
                score = 1.0
            else:
                losses += 1
                score = 0.0
            failures += int(outcome.termination in FAILED_TERMINATIONS)
            game = chess.pgn.read_game(io.StringIO(outcome.pgn))
            assert game is not None
            game.headers.update(
                {
                    "Event": "Local version comparison",
                    "White": str(white),
                    "Black": str(black),
                    "Opening": name,
                    "Date": datetime.now(UTC).strftime("%Y.%m.%d"),
                    "Termination": termination,
                    "Result": "1/2-1/2" if result == "draw" else game.headers["Result"],
                }
            )
            pgns.append(str(game))
            records.append(
                {
                    "opening": name,
                    "fen": fen,
                    "agent_white": as_white,
                    "result": result,
                    "termination": termination,
                    "score": score,
                    "plies": sum(1 for _ in game.mainline_moves()),
                }
            )
            print(
                f"{len(records)}/{args.pairs * 2} {name} "
                f"agent={'white' if as_white else 'black'}: {result} by {termination} "
                f"(+{wins} ={draws} -{losses})",
                flush=True,
            )
            args.out.with_suffix(".pgn").write_text("\n\n".join(pgns) + "\n", encoding="utf-8")
            report = {
                "agent": str(args.agent),
                "opponent": str(args.opponent),
                "agent_sha256": agent_hash,
                "opponent_sha256": opponent_hash,
                "suite": "external_positions" if args.positions_file else args.suite,
                "positions_file": str(args.positions_file) if args.positions_file else None,
                "base_ms": args.base_ms,
                "increment_ms": args.increment_ms,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "failures": failures,
                "score": (wins + draws / 2) / len(records),
                "games": records,
            }
            args.out.with_suffix(".json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
    print(f"Final: +{wins} ={draws} -{losses}, failures={failures}", flush=True)
    if failures:
        raise SystemExit("A game ended with an agent failure; inspect the report before accepting.")


if __name__ == "__main__":
    main()

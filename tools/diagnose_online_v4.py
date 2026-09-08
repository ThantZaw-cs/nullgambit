"""Private, clock-faithful v3/v4 probes; never change either frozen source."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import chess

from tools.online_review import read_games, sha256
from tools.validate_v4 import BASELINE_SHA256, CANDIDATE_SHA256, environment


def probe(
    module: Any, source: chess.Board, clock_ms: int, telemetry: bool
) -> dict[str, Any]:
    """Use real get_move; optional outer-call telemetry is not a different search."""
    before = source.fen(), [m.uci() for m in source.move_stack]
    previous = source.copy(stack=True)
    if previous.move_stack:
        previous.pop()
        module._previous_board = previous
    else:
        module._previous_board = None
    iterations: list[dict[str, Any]] = []
    root = module.compiled_root_search
    timed = module.timed_search
    restored: list[str] | None = None
    nodes: int | None = None

    def observed_root(*args: Any) -> tuple[int, int]:
        result = root(*args)
        counters = args[4]
        if not counters[1]:
            iterations.append(
                {
                    "depth": int(args[2]),
                    "score_cp": int(result[1]),
                    "move": module.move_to_uci(result[0]),
                    "nodes": int(counters[0]),
                }
            )
        return int(result[0]), int(result[1])

    def observed_timed(board: chess.Board, seconds: float) -> tuple[str, int, int]:
        nonlocal restored, nodes
        restored = [m.uci() for m in board.move_stack]
        if (board.fen(), restored) != before:
            raise RuntimeError("Real entry did not receive the full observed repetition history")
        result = timed(board, seconds)
        nodes = int(result[2])
        return str(result[0]), int(result[1]), int(result[2])

    if telemetry:
        module.compiled_root_search = observed_root
        module.timed_search = observed_timed
    try:
        started = time.monotonic()
        uci = module.get_move(source.fen(), clock_ms)
        elapsed = time.monotonic() - started
    finally:
        module.compiled_root_search = root
        module.timed_search = timed
    if chess.Move.from_uci(uci) not in source.legal_moves:
        raise RuntimeError("Frozen agent returned an illegal move")
    after = source.fen(), [m.uci() for m in source.move_stack]
    assert before == after
    stored_history = [m.uci() for m in module._previous_board.move_stack]
    if stored_history != before[1] + [uci]:
        raise RuntimeError("Real entry lost or invented repetition history")
    return {
        "move": uci,
        "san": source.san(chess.Move.from_uci(uci)),
        "depth": int(module.LAST_SEARCH_DEPTH),
        "elapsed_s": elapsed,
        "within_clock": elapsed * 1000 < clock_ms,
        "nodes": nodes,
        "iterations": iterations,
        "score_cp": iterations[-1]["score_cp"] if iterations else None,
        "history_verified": restored == before[1] if telemetry else True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/online/2026-09-08"))
    parser.add_argument("--rounds", nargs="+", default=["61", "62"])
    parser.add_argument("--last-fullmove", type=int, default=40)
    parser.add_argument("--select", nargs="*", help="Exact round:fullmove keys")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--telemetry", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from baselines.online_v3 import agent as v3
    from baselines.online_v4 import agent as v4

    assert sha256(Path(v3.__file__)) == BASELINE_SHA256
    assert sha256(Path(v4.__file__)) == CANDIDATE_SHA256
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise RuntimeError("Refusing to overwrite a previous diagnostic run")
    report: dict[str, Any] = {
        "environment": environment(),
        "telemetry": args.telemetry,
        "v3_sha256": BASELINE_SHA256,
        "v4_sha256": CANDIDATE_SHA256,
        "note": "Same hardware and real get_move time policy. Outer Python "
        "telemetry adds small overhead; repeat selected cases uninstrumented.",
        "positions": [],
    }
    for metadata, game in read_games(args.directory):
        if metadata["round"] not in args.rounds:
            continue
        board = game.board()
        for row in metadata["moves"]:
            key = f"{metadata['round']}:{row['fullmove']}"
            selected = (
                (key in args.select)
                if args.select is not None
                else (row["fullmove"] <= args.last_fullmove)
            )
            if row["ours"] and selected:
                history = [m.uci() for m in board.move_stack]
                clock_ms = round(row["clock_before_s"] * 1000)
                record = {
                    "key": key,
                    "position": row,
                    "start_fen": game.board().fen(),
                    "history": history,
                    "history_sha256": hashlib.sha256(" ".join(history).encode()).hexdigest(),
                    "clock_ms": clock_ms,
                    "runs": [],
                }
                for repetition in range(args.repeats):
                    modules = [("v3", v3), ("v4", v4)]
                    if (len(report["positions"]) + repetition) % 2:
                        modules.reverse()
                    for label, module in modules:
                        result = probe(module, board, clock_ms, args.telemetry)
                        record["runs"].append(
                            {"version": label, "repeat": repetition + 1, **result}
                        )
                        print(
                            key,
                            row["san"],
                            label,
                            repetition + 1,
                            result["san"],
                            result["depth"],
                            result["score_cp"],
                            flush=True,
                        )
                report["positions"].append(record)
                args.out.write_text(json.dumps(report, indent=2) + "\n")
            board.push_uci(row["uci"])


if __name__ == "__main__":
    main()

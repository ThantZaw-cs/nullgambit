"""Repeat real entries with complete history; optional extra time is diagnosis only."""

import argparse
import importlib
import json
import time
from pathlib import Path
from typing import Any

import chess
import numpy as np

from tools.online_review import sha256
from tools.release_environment import environment


def probe(
    module: Any, source: chess.Board, clock_ms: int, multiplier: float = 1.0
) -> dict[str, Any]:
    before = source.fen(), [m.uci() for m in source.move_stack]
    previous = source.copy(stack=True)
    if previous.move_stack:
        previous.pop()
        module._previous_board = previous
    else:
        module._previous_board = None
    root, timed = module.compiled_root_search, module.timed_search
    iterations: list[dict[str, Any]] = []
    restored = False
    budgets: list[float] = []
    started = time.monotonic()

    def observed_root(*args: Any) -> tuple[int, int]:
        board, state = args[0].copy(), args[1].copy()
        tick = time.monotonic()
        move, score = root(*args)
        elapsed = time.monotonic() - tick
        assert np.array_equal(board, args[0]) and np.array_equal(state, args[1])
        complete = not bool(args[4][1])
        iterations.append(
            {
                "depth": int(args[2]),
                "complete": complete,
                "move": module.move_to_uci(move) if complete else None,
                "score_cp": int(score) if complete else None,
                "nodes": int(args[4][0]),
                "elapsed_s": elapsed,
                "cumulative_s": time.monotonic() - started,
            }
        )
        return int(move), int(score)

    def observed_timed(board: chess.Board, seconds: float, *args: Any) -> tuple[str, int, int]:
        nonlocal restored
        assert (board.fen(), [m.uci() for m in board.move_stack]) == before
        restored = True
        budgets.append(seconds * multiplier)
        return timed(board, seconds * multiplier, *args)  # type: ignore[no-any-return]

    module.compiled_root_search, module.timed_search = observed_root, observed_timed
    try:
        move = module.get_move(source.fen(), clock_ms)
        elapsed = time.monotonic() - started
    finally:
        module.compiled_root_search, module.timed_search = root, timed
    assert chess.Move.from_uci(move) in source.legal_moves
    assert (source.fen(), [m.uci() for m in source.move_stack]) == before
    assert [m.uci() for m in module._previous_board.move_stack] == before[1] + [move]
    complete = [r for r in iterations if r["complete"]]
    return {
        "move": move,
        "san": source.san(chess.Move.from_uci(move)),
        "depth": module.LAST_SEARCH_DEPTH,
        "elapsed_s": elapsed,
        "clock_ms": clock_ms,
        "within_clock": elapsed * 1000 < clock_ms,
        "budget_multiplier": multiplier,
        "search_budgets_s": budgets,
        "history_verified": restored or not budgets,
        "unmake_verified": True,
        "score_cp": complete[-1]["score_cp"] if complete else None,
        "iterations": iterations,
        "aborted_fraction": sum(r["elapsed_s"] for r in iterations if not r["complete"]) / elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--select", nargs="*")
    parser.add_argument(
        "--modules", nargs="+", default=["baselines.online_v3.agent", "baselines.online_v4.agent"]
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--multiplier", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise RuntimeError("Refusing to overwrite measured evidence")
    modules = [(name, importlib.import_module(name)) for name in args.modules]
    hashes = {}
    for name, module in modules:
        assert module.__file__ is not None
        hashes[name] = sha256(Path(module.__file__))
    metadata = {
        "environment": environment(),
        "source_positions_sha256": sha256(args.positions),
        "modules": hashes,
        "multiplier": args.multiplier,
        "repeats": args.repeats,
        "order": "alternate versions per position/repeat; sequential on one machine",
    }
    args.out.with_suffix(".meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
    positions = [json.loads(s) for s in args.positions.read_text().splitlines()]
    with args.out.open("x") as out:
        for i, row in enumerate(positions):
            if args.select is not None and row["key"] not in args.select:
                continue
            board = chess.Board(row["start_fen"])
            for uci in row["history"]:
                board.push_uci(uci)
            assert board.fen() == row["position"]["fen"]
            clock = round(row["position"]["clock_before_s"] * 1000)
            for repetition in range(args.repeats):
                order = modules if (i + repetition) % 2 == 0 else list(reversed(modules))
                for name, module in order:
                    result = probe(module, board, clock, args.multiplier)
                    record = {"key": row["key"], "module": name, "repeat": repetition + 1, **result}
                    out.write(json.dumps(record) + "\n")
                    out.flush()
                    print(
                        row["key"],
                        name,
                        repetition + 1,
                        result["san"],
                        result["depth"],
                        round(result["elapsed_s"], 3),
                        round(result["aborted_fraction"], 2),
                        flush=True,
                    )


if __name__ == "__main__":
    main()

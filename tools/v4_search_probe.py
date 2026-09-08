"""Isolated subprocess probe; instrumentation stays outside the submission ZIP."""

import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

import chess


def main() -> None:
    directory = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(directory))
    started = time.monotonic()
    candidate = importlib.import_module("agent")
    initialization = time.monotonic() - started
    if candidate.__file__ is None:
        raise RuntimeError("Imported agent has no source file")
    loaded = Path(candidate.__file__).resolve()
    if loaded != directory / "agent.py":
        raise RuntimeError(f"Imported the wrong agent: {loaded}")
    checks = []
    board = chess.Board()
    for remaining in (5000, 1000):
        started = time.monotonic()
        uci = candidate.get_move(board.fen(), remaining)
        elapsed = (time.monotonic() - started) * 1000
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves or candidate.LAST_SEARCH_DEPTH <= 0:
            raise RuntimeError("The packaged entry must return a legal move after real search")
        if elapsed >= remaining:
            raise RuntimeError("The packaged entry exceeded its remaining clock")
        checks.append(
            {
                "fen": board.fen(),
                "remaining_ms": remaining,
                "move": uci,
                "elapsed_ms": elapsed,
                "completed_depth": candidate.LAST_SEARCH_DEPTH,
            }
        )
        board.push(move)
        board.push(next(iter(board.legal_moves)))
    print(
        json.dumps(
            {
                "agent_sha256": hashlib.sha256(loaded.read_bytes()).hexdigest(),
                "init_seconds": initialization,
                "checks": checks,
            }
        )
    )


if __name__ == "__main__":
    main()

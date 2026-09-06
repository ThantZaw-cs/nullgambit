"""Measure equal-time search throughput against a saved engine."""

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import TypedDict

import chess

import agent
from baselines.classical_v1 import agent as previous_v1
from baselines.classical_v2 import agent as previous_v2
from tools.positions import positions


class SearchResult(TypedDict):
    nodes: int
    depth: int
    elapsed_s: float
    nodes_per_second: float
    move: str


class PositionResult(TypedDict):
    opening: str
    fen: str
    previous: SearchResult
    current: SearchResult


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--reference", choices=("v1", "v2"), default="v2")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/positional-performance.json"))
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    reference = previous_v2 if args.reference == "v2" else previous_v1
    rows: list[PositionResult] = []
    for name, fen in positions():
        results: dict[str, SearchResult] = {}
        for label, module in (("previous", reference), ("current", agent)):
            board = chess.Board(fen)
            started = time.monotonic()
            search = module.Search(started + args.seconds)
            move = search.choose(board, next(iter(board.legal_moves)))
            elapsed = time.monotonic() - started
            assert move in board.legal_moves and board.fen() == fen
            results[label] = {
                "nodes": search.nodes,
                "depth": search.completed_depth,
                "elapsed_s": elapsed,
                "nodes_per_second": search.nodes / elapsed,
                "move": move.uci(),
            }
        rows.append(
            {
                "opening": name,
                "fen": fen,
                "previous": results["previous"],
                "current": results["current"],
            }
        )
        print(f"{name}: previous={results['previous']} current={results['current']}", flush=True)
    # Report elapsed-time-normalized throughput; completed depths are also in the
    # raw data because extensions and reductions change the cost of a search ply.
    old_nps = statistics.median(float(row["previous"]["nodes_per_second"]) for row in rows)
    new_nps = statistics.median(float(row["current"]["nodes_per_second"]) for row in rows)
    report = {
        "reference": args.reference,
        "reference_sha256": hashlib.sha256(
            Path(f"baselines/classical_{args.reference}/agent.py").read_bytes()
        ).hexdigest(),
        "seconds_per_position": args.seconds,
        "agent_sha256": hashlib.sha256(Path("agent.py").read_bytes()).hexdigest(),
        "previous_median_nps": old_nps,
        "current_median_nps": new_nps,
        "throughput_ratio": new_nps / old_nps,
        "positions": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Median throughput ratio: {new_nps / old_nps:.2f}x", flush=True)


if __name__ == "__main__":
    main()

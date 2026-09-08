"""Paired search measurements on a declared, private online development set."""

import json
import platform
from pathlib import Path
from typing import Any

import chess

from baselines.online_v3 import agent as online_v3
from prototypes.numba_kernel import agent as candidate
from tools.online_review import read_games, search, sha256


def main() -> None:
    selection = {"58": {14, 16, 17, 18, 27, 31}, "60": {7, 8, 12, 23, 29, 34}}
    games = read_games(Path("data/online/2026-09-08"))
    report: dict[str, Any] = {
        "candidate_sha256": sha256(Path(candidate.__file__)),
        "baseline_sha256": sha256(Path(online_v3.__file__)),
        "platform": platform.platform(),
        "description": "Online rounds 58/60 are development, never blind validation. "
        "Same fixed depth, then equal wall-time budgets; sequential, alternating engine order.",
        "positions": [],
    }
    target = Path("benchmarks/astra-v4/development-search.json")
    for metadata, game in games:
        board = game.board()
        for row in metadata["moves"]:
            if row["ours"] and row["fullmove"] in selection.get(metadata["round"], set()):
                record: dict[str, Any] = {
                    "id": f"r{metadata['round']}-m{row['fullmove']}",
                    "fen": board.fen(), "history_plies": len(board.move_stack),
                    "online_move": row["uci"], "clock_before_s": row["clock_before_s"],
                    "fixed_depth_5": {}, "timed": {},
                }
                modules = [("baseline", online_v3), ("candidate", candidate)]
                if len(report["positions"]) % 2:
                    modules.reverse()
                for label, module in modules:
                    record["fixed_depth_5"][label] = search(module, board, 30.0, 5)
                first, second = record["fixed_depth_5"].values()
                assert first["depth"] == second["depth"] == 5
                assert first["score_cp"] == second["score_cp"], record
                for seconds in (0.1, 0.5, 2.5):
                    record["timed"][str(seconds)] = {
                        label: search(module, board, seconds) for label, module in modules
                    }
                report["positions"].append(record)
                target.write_text(json.dumps(report, indent=2) + "\n")
                print(record["id"], "fixed nodes", {
                    k: v["nodes"] for k, v in record["fixed_depth_5"].items()
                }, "2.5s depth", {
                    k: v["depth"] for k, v in record["timed"]["2.5"].items()
                }, flush=True)
            board.push(chess.Move.from_uci(row["uci"]))


if __name__ == "__main__":
    main()

"""Compare recorded decisions at a common depth, preserving real repetition history.

Scores use our own unchanged evaluator and are hypotheses, not external ground truth.
"""

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from prototypes.numba_kernel import agent
from tools.online_review import read_games, search, sha256


def main() -> None:
    # These games are all development/review data, never holdout data.
    selection = {"58": {15, 16, 17, 18, 33}, "60": {7, 8, 23, 29, 34, 36},
                 "54": {25, 27, 56, 59}}
    games = read_games(Path("data/online/2026-09-08"))
    report: dict[str, Any] = {"agent_sha256": sha256(Path(agent.__file__)), "positions": []}
    target = Path("data/online/2026-09-08/derived/decision-probes.json")
    for metadata, game in sorted(games, key=lambda pair: {"58": 0, "60": 1, "54": 2}.get(
        pair[0]["round"], 3
    )):
        source = game.board()
        for row in metadata["moves"]:
            if row["ours"] and row["fullmove"] in selection.get(metadata["round"], set()):
                before = source.copy(stack=True)
                best = search(agent, before, 8.0, 6)
                source.push_uci(row["uci"])
                board, state = agent.from_chess(source)
                history = np.zeros(256, dtype=np.uint64)
                length = agent._seed_history(source, history)
                counters = np.zeros(4, dtype=np.int64)
                recorded_score = -agent._negamax(
                    board, state, best["depth"] - 1, -101_000, 101_000, 1,
                    time.monotonic() + 8.0, counters, history, length,
                    np.zeros(agent.TT_LIMIT, dtype=np.uint64),
                    np.full(agent.TT_LIMIT, -1, dtype=np.int64),
                    np.zeros((2, 64, 64), dtype=np.int64),
                )
                source.pop()
                record = {"round": metadata["round"], "fullmove": row["fullmove"],
                          "online_san": row["san"], "clock_before_s": row["clock_before_s"],
                          "fen": source.fen(), "history_plies": len(source.move_stack),
                          "best": best, "recorded_score_cp": recorded_score,
                          "recorded_aborted": bool(counters[1]),
                          "recorded_nodes": int(counters[0])}
                report["positions"].append(record)
                target.write_text(json.dumps(report, indent=2) + "\n")
                print(metadata["round"], row["fullmove"], row["san"],
                      "depth", best["depth"], "best", best["move"], best["score_cp"],
                      "recorded", recorded_score, "aborted", bool(counters[1]), flush=True)
            source.push_uci(row["uci"])


if __name__ == "__main__":
    main()

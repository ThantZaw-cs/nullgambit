"""Audit the fixed Linux control, including original PGNs and per-move traces."""

import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import chess.pgn
import numpy as np

from harness.referee import FAILED_TERMINATIONS
from tools.online_review import sha256
from tools.validate_v4 import BASELINE_SHA256, CANDIDATE_SHA256

ROOT = Path(__file__).resolve().parents[1]


def summarize(directory: Path) -> dict[str, Any]:
    report = json.loads((directory / "formal.json").read_text())
    plan = json.loads((directory / "plan.json").read_text())
    assert report["plan_sha256"] == sha256(directory / "plan.json")
    assert report["plan_sha256"] == sha256(ROOT / "benchmarks/astra-v4-diagnosis/plan.json")
    assert report["candidate_sha256"] == CANDIDATE_SHA256
    assert report["opponent_sha256"] == BASELINE_SHA256
    for key in ("candidate_sha256", "opponent_sha256"):
        assert report[key] == plan[key]
    assert plan["base_ms"] == 120_000 and plan["increment_ms"] == 500
    assert len(plan["openings"]) == len({row["fen"] for row in plan["openings"]}) == 10
    rows = report["games"]
    assert len(rows) <= 20 and report["actual_games"] == len(rows)
    assert report["requested_games"] == 20
    assert (report["status"] == "completed") == (len(rows) == 20)
    pairs: dict[str, list[float]] = {}
    for index, row in enumerate(rows):
        assert row["index"] == index + 1
        opening = plan["openings"][index // 2]
        assert row["opening"] == opening["name"] and row["fen"] == opening["fen"]
        assert row["candidate_white"] == (index % 2 == 0)
        with (directory / f"game-{index + 1:02d}.pgn").open() as handle:
            game = chess.pgn.read_game(handle)
        assert game is not None and not game.errors
        assert game.board().fen() == opening["fen"]
        assert game.headers["White"] == ("v4" if row["candidate_white"] else "v3")
        assert game.headers["Black"] == ("v3" if row["candidate_white"] else "v4")
        assert game.headers["Result"] == {
            "white": "1-0", "black": "0-1", "draw": "1/2-1/2", "void": "*"
        }[row["result"]]
        trace = [
            json.loads(line)
            for line in (directory / f"game-{index + 1:02d}.jsonl").read_text().splitlines()
        ]
        init = [entry for entry in trace if entry["event"] == "init"]
        assert len(init) == 2 and {entry["side"] for entry in init} == {"white", "black"}
        moves = [entry for entry in trace if entry["event"] == "move"]
        board = game.board()
        pgn_moves = list(game.mainline_moves())
        assert len(pgn_moves) == row["plies"]
        if row["termination"] not in FAILED_TERMINATIONS:
            assert len(moves) == len(pgn_moves)
        for ply, move in enumerate(pgn_moves):
            assert moves[ply]["fen"] == board.fen()
            assert moves[ply]["side"] == ("white" if board.turn else "black")
            assert moves[ply]["move"] == move.uci() and move in board.legal_moves
            board.push(move)
        if row["termination"] not in FAILED_TERMINATIONS | {"adjudication"}:
            finish = board.outcome(claim_draw=True)
            assert finish is not None and finish.result() == game.headers["Result"]
        if row["result"] != "void":
            score = (
                0.5
                if row["result"] == "draw"
                else float((row["result"] == "white") == row["candidate_white"])
            )
            pairs.setdefault(row["opening"], []).append(score)
    wins = sum(
        row["result"] in {"white", "black"}
        and ((row["result"] == "white") == row["candidate_white"])
        for row in rows
    )
    losses = sum(
        row["result"] in {"white", "black"}
        and ((row["result"] == "white") != row["candidate_white"])
        for row in rows
    )
    draws = sum(row["result"] == "draw" for row in rows)
    voids = sum(row["result"] == "void" for row in rows)
    assert report["failures"] == sum(row["termination"] in FAILED_TERMINATIONS for row in rows)
    assert report["adjudications"] == sum(row["termination"] == "adjudication" for row in rows)
    assert (wins, draws, losses, voids) == tuple(
        report[key] for key in ("wins", "draws", "losses", "voids")
    )
    paired_scores = np.asarray([sum(scores) / 2 for scores in pairs.values() if len(scores) == 2])
    interval = None
    sign_p = None
    if len(paired_scores):
        rng = np.random.default_rng(20260908)
        bootstrap = rng.choice(paired_scores, (200_000, len(paired_scores))).mean(axis=1)
        interval = np.quantile(bootstrap, [0.025, 0.975]).tolist()
        positive, negative = int(np.sum(paired_scores > 0.5)), int(np.sum(paired_scores < 0.5))
        decisive = positive + negative
        if decisive:
            sign_p = min(
                1.0,
                2
                * sum(math.comb(decisive, k) for k in range(max(positive, negative), decisive + 1))
                / 2**decisive,
            )
    elapsed = (
        datetime.fromisoformat(report["finished_utc"])
        - datetime.fromisoformat(report["started_utc"])
    ).total_seconds()
    return {
        "requested_games": 20,
        "actual_games": len(rows),
        "complete": len(rows) == 20,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "voids": voids,
        "failures": report["failures"],
        "adjudications": report["adjudications"],
        "raw_referee_score": (wins + draws / 2) / (wins + draws + losses)
        if wins + draws + losses
        else None,
        "terminations": dict(Counter(row["termination"] for row in rows)),
        "paired_scores": paired_scores.tolist(),
        "pair_bootstrap_95": interval,
        "descriptive_two_sided_pair_sign_p": sign_p,
        "elapsed_s": elapsed,
        "plan_sha256": report["plan_sha256"],
        "candidate_sha256": report["candidate_sha256"],
        "opponent_sha256": report["opponent_sha256"],
        "all_completed_pgns_and_traces_audited": True,
        "interpretation": "Previously used regression openings, one opponent, ten pairs. "
        "Small-sample descriptive uncertainty; not an Elo estimate or official container test. "
        "Raw referee scores are preserved; any cap adjudications must be considered separately.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = summarize(args.directory)
    (args.directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

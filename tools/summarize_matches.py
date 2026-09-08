"""Audit completed paired match artifacts and summarize pair-level uncertainty."""

import argparse
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess.pgn
import numpy as np


def summarize(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    rows = report["games"]
    paired: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        paired.setdefault(row["opening"], []).append(row)
    assert all(len(pair) == 2 for pair in paired.values()), "Incomplete opening pair"
    for pair in paired.values():
        assert {row["agent_white"] for row in pair} == {True, False}
        assert len({row["fen"] for row in pair}) == 1
    pgns = []
    with path.with_suffix(".pgn").open() as handle:
        while (game := chess.pgn.read_game(handle)) is not None:
            assert not game.errors
            pgns.append(game)
    assert len(pgns) == len(rows)
    for row, game in zip(rows, pgns, strict=True):
        assert game.headers["White"] == (
            report["agent"] if row["agent_white"] else report["opponent"]
        )
        if row["result"] != "void":
            expected_score = 0.5 if row["result"] == "draw" else float(
                (row["result"] == "white") == row["agent_white"]
            )
            assert row["score"] == expected_score
        board = game.board()
        assert board.fen() == row["fen"]
        for move in game.mainline_moves():
            assert move in board.legal_moves
            board.push(move)
        assert len(board.move_stack) == row["plies"]
        if row["termination"] not in {"ply_cap", "crash", "illegal", "flag", "init", "both_failed"}:
            outcome = board.outcome(claim_draw=True)
            assert outcome is not None and outcome.result() == game.headers["Result"]
    wins = sum(row["result"] in {"white", "black"} and
               ((row["result"] == "white") == row["agent_white"]) for row in rows)
    losses = sum(row["result"] in {"white", "black"} and
                 ((row["result"] == "white") != row["agent_white"]) for row in rows)
    draws = sum(row["result"] == "draw" for row in rows)
    voids = sum(row["result"] == "void" for row in rows)
    assert (wins, draws, losses) == (report["wins"], report["draws"] - voids, report["losses"])
    valid_pairs = [pair for pair in paired.values() if all(row["result"] != "void" for row in pair)]
    pair_scores = np.asarray([sum(row["score"] for row in pair) / 2 for pair in valid_pairs])
    rng = np.random.default_rng(20260908)
    interval = None
    if len(pair_scores):
        bootstrap = rng.choice(pair_scores, (200_000, len(pair_scores))).mean(axis=1)
        interval = np.quantile(bootstrap, [0.025, 0.975]).tolist()
    positive = int(np.sum(pair_scores > 0.5))
    negative = int(np.sum(pair_scores < 0.5))
    decisive_pairs = positive + negative
    sign_p = None
    if decisive_pairs:
        tail = sum(math.comb(decisive_pairs, k) for k in range(
            max(positive, negative), decisive_pairs + 1
        )) / 2 ** decisive_pairs
        sign_p = min(1.0, 2.0 * tail)
    log = path.with_suffix(".log").stat()
    start = getattr(log, "st_birthtime", None)
    return {
        "source": str(path), "agent_sha256": report["agent_sha256"],
        "opponent_sha256": report["opponent_sha256"], "games": len(rows),
        "pairs": len(paired), "wins": wins, "draws": draws, "losses": losses,
        "voids": voids, "failures": report["failures"],
        "terminations": dict(Counter(row["termination"] for row in rows)),
        "score": (wins + draws / 2) / (wins + draws + losses) if wins + draws + losses else None,
        "pair_scores": pair_scores.tolist(), "pair_bootstrap_95": interval,
        "positive_negative_tied_pairs": [positive, negative, len(pair_scores) - decisive_pairs],
        "descriptive_two_sided_pair_sign_p": sign_p,
        "uncertainty_note": "Exploratory paired bootstrap; few pairs and a single opponent "
        "do not establish Elo or general strength. Voids are excluded, never counted as draws.",
        "base_ms": report["base_ms"], "increment_ms": report["increment_ms"],
        "all_pgns_replayed_legally": True,
        "started_utc": datetime.fromtimestamp(start, UTC).isoformat() if start else None,
        "finished_utc": datetime.fromtimestamp(log.st_mtime, UTC).isoformat(),
        "elapsed_s": log.st_mtime - start if start else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    summary = summarize(args.report)
    target = args.report.with_name(args.report.stem + "-summary.json")
    target.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

"""Execute a fixed candidate/v4 paired plan, preserving every raw referee outcome."""

import argparse
import io
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess
import chess.pgn

from harness.referee import FAILED_TERMINATIONS
from tools.formal_v4_control import RecordedAgent, stop_on_budget
from tools.online_review import sha256
from tools.release_environment import environment
from tools.release_referee import play_match
from tools.validate_v4 import CANDIDATE_SHA256

ROOT = Path(__file__).resolve().parents[1]


def checkpoint(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    assert plan["requested_games"] == 2 * len(plan["openings"])
    assert plan["requested_games"] == 20
    assert (plan["base_ms"], plan["increment_ms"], plan["ply_cap"]) == (120000, 500, 600)
    assert len({r["fen"] for r in plan["openings"]}) == len(plan["openings"])
    assert all(chess.Board(r["fen"]).is_valid() for r in plan["openings"])
    assert sys.platform == plan["platform"]
    assert sys.version_info[:2] == (3, 12)
    assert plan["opponent_sha256"] == CANDIDATE_SHA256
    candidate, baseline = ROOT / plan["candidate_directory"], ROOT / "baselines/online_v4"
    label = plan["candidate_name"]
    if sys.platform == "linux":
        import os
        import platform

        assert platform.machine() == "x86_64"
        assert len(os.sched_getaffinity(0)) == 1
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    (out / "plan.json").write_bytes(args.plan.read_bytes())
    (out / "environment.json").write_text(json.dumps(environment(), indent=2) + "\n")
    report: dict[str, Any] = {
        "plan_sha256": sha256(args.plan),
        "started_utc": datetime.now(UTC).isoformat(),
        "candidate_sha256": plan["candidate_sha256"],
        "opponent_sha256": plan["opponent_sha256"],
        "requested_games": plan["requested_games"],
        "status": "running",
        "games": [],
    }
    signal.signal(signal.SIGTERM, stop_on_budget)
    signal.signal(signal.SIGALRM, stop_on_budget)
    signal.alarm(plan["execution_limit_s"])
    try:
        for opening in plan["openings"]:
            for as_white in (True, False):
                for directory, key in (
                    (candidate, "candidate_sha256"),
                    (baseline, "opponent_sha256"),
                ):
                    assert sha256(directory / "agent.py") == plan[key]
                index = len(report["games"]) + 1
                white_path, black_path = (
                    (candidate, baseline) if as_white else (baseline, candidate)
                )
                trace = out / f"game-{index:02d}.jsonl"
                white, black = (
                    RecordedAgent(white_path, trace, "white"),
                    RecordedAgent(black_path, trace, "black"),
                )
                started = time.monotonic()
                report["pending_game"] = {
                    "index": index,
                    "opening": opening["name"],
                    "candidate_white": as_white,
                }
                checkpoint(out / "results.json", report)
                outcome = play_match(
                    white,
                    black,
                    plan["base_ms"],
                    plan["increment_ms"],
                    start_fen=opening["fen"],
                    ply_cap=plan["ply_cap"],
                    record=white.record,
                )
                game = chess.pgn.read_game(io.StringIO(outcome.pgn))
                assert game is not None and not game.errors
                game.headers.update(
                    {
                        "White": label if as_white else "v4",
                        "Black": "v4" if as_white else label,
                        "Opening": opening["name"],
                        "Round": str(index),
                        "Event": "Predeclared Linux astra-v7 release control",
                        "TimeControl": "120+0.5",
                    }
                )
                board = game.board()
                assert board.fen() == opening["fen"]
                for move in game.mainline_moves():
                    assert move in board.legal_moves
                    board.push(move)
                row = {
                    "index": index,
                    "opening": opening["name"],
                    "fen": opening["fen"],
                    "candidate_white": as_white,
                    "result": outcome.result,
                    "termination": outcome.termination,
                    "plies": len(board.move_stack),
                    "total_plies": board.ply(),
                    "elapsed_s": time.monotonic() - started,
                    "white_stderr": white.stderr_tail,
                    "black_stderr": black.stderr_tail,
                }
                checkpoint(out / f"game-{index:02d}.result.json", row)
                report["games"].append(row)
                report.pop("pending_game", None)
                (out / f"game-{index:02d}.pgn").write_text(str(game) + "\n")
                checkpoint(out / "results.json", report)
                print(json.dumps(row), flush=True)
        report["status"] = "completed"
    except BaseException as error:
        report.update({"status": "incomplete", "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        signal.alarm(0)
        rows = report["games"]
        report["finished_utc"] = datetime.now(UTC).isoformat()
        report["actual_games"] = len(rows)
        report["wins"] = sum(
            r["result"] in {"white", "black"} and ((r["result"] == "white") == r["candidate_white"])
            for r in rows
        )
        report["losses"] = sum(
            r["result"] in {"white", "black"} and ((r["result"] == "white") != r["candidate_white"])
            for r in rows
        )
        report["draws"] = sum(r["result"] == "draw" for r in rows)
        report["voids"] = sum(r["result"] == "void" for r in rows)
        report["failures"] = sum(r["termination"] in FAILED_TERMINATIONS for r in rows)
        report["ply_cap_draws"] = sum(r["termination"] == "ply_cap_draw" for r in rows)
        report["adjudications"] = sum(r["termination"] == "adjudication" for r in rows)
        checkpoint(out / "results.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "games"}), flush=True)


if __name__ == "__main__":
    main()

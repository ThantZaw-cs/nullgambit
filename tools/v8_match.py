"""Execute a fixed candidate/v7 paired plan, preserving every raw referee outcome."""

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

V7_SHA256 = "aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d"

ROOT = Path(__file__).resolve().parents[1]


def checkpoint(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def save_interrupted(
    out: Path,
    report: dict[str, Any],
    plan: dict[str, Any],
    opening: dict[str, Any],
    as_white: bool,
    started: float,
    error: BaseException,
) -> None:
    """Persist an interrupted game as VOID; a resume cannot replay its opening/color."""
    index = len(report["games"]) + 1
    trace = out / f"game-{index:02d}.jsonl"
    board = chess.Board(opening["fen"])
    pending_move: dict[str, Any] | None = None
    for line in trace.read_text().splitlines() if trace.exists() else []:
        entry = json.loads(line)
        if entry["event"] == "move":
            pending_move = entry
        elif entry["event"] == "clock" and entry["accepted"]:
            assert pending_move is not None and pending_move["fen"] == board.fen()
            move = chess.Move.from_uci(pending_move["move"])
            assert move in board.legal_moves
            board.push(move)
            pending_move = None
    game = chess.pgn.Game.from_board(board)
    label = plan["candidate_name"]
    game.headers.update(
        {
            "White": label if as_white else "v7",
            "Black": "v7" if as_white else label,
            "Opening": opening["name"],
            "Round": str(index),
            "Result": "*",
            "Termination": "infrastructure_interruption",
        }
    )
    row = {
        "index": index,
        "opening": opening["name"],
        "fen": opening["fen"],
        "candidate_white": as_white,
        "result": "void",
        "termination": "infrastructure_interruption",
        "plies": len(board.move_stack),
        "total_plies": board.ply(),
        "elapsed_s": time.monotonic() - started,
        "error": f"{type(error).__name__}: {error}",
        "white_stderr": "See preserved trace",
        "black_stderr": "See preserved trace",
    }
    (out / f"game-{index:02d}.pgn").write_text(str(game) + "\n")
    checkpoint(out / f"game-{index:02d}.result.json", row)
    report["games"].append(row)
    report.pop("pending_game", None)
    checkpoint(out / "results.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--resume", action="store_true", help="Continue only unscheduled games; never replay a VOID"
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    assert plan["requested_games"] == 2 * len(plan["openings"])
    expected = {"fast": (40, 10000, 100), "formal": (20, 120000, 500)}[plan["stage"]]
    assert (plan["requested_games"], plan["base_ms"], plan["increment_ms"]) == expected
    assert plan["ply_cap"] == 600
    assert all(
        plan["gate"][key]
        for key in (
            "candidate_frozen",
            "correctness_passed",
            "development_positive",
            "holdout_passed",
        )
    )
    if plan["stage"] == "formal":
        assert plan["gate"]["fast_screen_passed"]
    assert len({r["fen"] for r in plan["openings"]}) == len(plan["openings"])
    assert all(chess.Board(r["fen"]).is_valid() for r in plan["openings"])
    assert sys.platform in plan["allowed_platforms"]
    assert sys.version_info[:2] == (3, 12)
    assert plan["opponent_sha256"] == V7_SHA256
    assert plan["opponent_name"] == "v7"
    candidate, baseline = ROOT / plan["candidate_directory"], ROOT / plan["opponent_directory"]
    assert baseline.resolve() == (ROOT / "baselines/online_v7").resolve()
    for directory, key in ((candidate, "candidate_sha256"), (baseline, "opponent_sha256")):
        assert sha256(directory / "agent.py") == plan[key]
    label = plan["candidate_name"]
    if sys.platform == "linux":
        import os
        import platform
        import resource

        assert resource.getrlimit(resource.RLIMIT_AS)[0] == 2 * 1024**3
        assert platform.machine() == "x86_64"
        assert len(os.sched_getaffinity(0)) == 1
    out = args.out
    if args.resume:
        assert out.is_dir()
        assert (out / "plan.json").read_bytes() == args.plan.read_bytes()
    else:
        out.mkdir(parents=True, exist_ok=False)
    (out / "plan.json").write_bytes(args.plan.read_bytes())
    environment_name = (
        f"environment-resume-{time.time_ns()}.json" if args.resume else "environment.json"
    )
    (out / environment_name).write_text(json.dumps(environment(), indent=2) + "\n")
    report: dict[str, Any] = {
        "plan_sha256": sha256(args.plan),
        "started_utc": datetime.now(UTC).isoformat(),
        "candidate_sha256": plan["candidate_sha256"],
        "opponent_sha256": plan["opponent_sha256"],
        "requested_games": plan["requested_games"],
        "status": "running",
        "games": [],
    }
    if args.resume:
        report = json.loads((out / "results.json").read_text())
        assert report["status"] == "incomplete" and "pending_game" not in report
        assert len(report["games"]) < plan["requested_games"]
        report["status"] = "running"
        report.setdefault("resumed_utc", []).append(datetime.now(UTC).isoformat())
    session_started = time.monotonic()
    elapsed_before = report.get("execution_elapsed_s", 0.0)
    remaining = plan["execution_limit_s"] - elapsed_before
    assert remaining > 0, "The original batch execution cap is exhausted"
    signal.signal(signal.SIGTERM, stop_on_budget)
    signal.signal(signal.SIGALRM, stop_on_budget)
    signal.alarm(max(1, int(remaining)))
    try:
        for opening_index, opening in enumerate(plan["openings"]):
            for color_index, as_white in enumerate((True, False)):
                scheduled_index = 2 * opening_index + color_index + 1
                if scheduled_index <= len(report["games"]):
                    continue
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
                try:
                    outcome = play_match(
                        white,
                        black,
                        plan["base_ms"],
                        plan["increment_ms"],
                        start_fen=opening["fen"],
                        ply_cap=plan["ply_cap"],
                        record=white.record,
                    )
                except BaseException as error:
                    save_interrupted(out, report, plan, opening, as_white, started, error)
                    raise
                game = chess.pgn.read_game(io.StringIO(outcome.pgn))
                assert game is not None and not game.errors
                game.headers.update(
                    {
                        "White": label if as_white else "v7",
                        "Black": "v7" if as_white else label,
                        "Opening": opening["name"],
                        "Round": str(index),
                        "Event": "Predeclared astra-v8 search control",
                        "TimeControl": (
                            f"{plan['base_ms'] / 1000:g}+{plan['increment_ms'] / 1000:g}"
                        ),
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
        report["execution_elapsed_s"] = elapsed_before + time.monotonic() - session_started
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

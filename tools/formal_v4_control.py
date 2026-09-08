"""One predeclared 20-game Linux control; preserve raw referee results and move clocks."""

import argparse
import io
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

import chess
import chess.pgn

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.sandbox import Agent, local
from tools.online_review import sha256
from tools.validate_v4 import environment

ROOT = Path(__file__).resolve().parents[1]


class RecordedAgent(Agent):
    def __init__(self, directory: Path, trace: Path, side: str) -> None:
        super().__init__(local(directory).command)
        self.trace = trace
        self.side = side

    def record(self, row: dict[str, Any]) -> None:
        with self.trace.open("a") as handle:
            handle.write(
                json.dumps({"utc": datetime.now(UTC).isoformat(), "side": self.side, **row}) + "\n"
            )

    def start(self, init_budget_s: float) -> None:
        started = time.monotonic()
        try:
            super().start(init_budget_s)
        finally:
            self.record({"event": "init", "elapsed_s": time.monotonic() - started})

    def move(self, fen: str, time_left_ms: int) -> str:
        started = time.monotonic()
        row: dict[str, Any] = {"event": "move", "fen": fen, "remaining_ms": time_left_ms}
        try:
            move = super().move(fen, time_left_ms)
            row["move"] = move
            return move
        except Exception as error:
            row["error"] = str(error)
            raise
        finally:
            row["round_trip_ms"] = (time.monotonic() - started) * 1000
            self.record(row)


def stop_on_budget(signum: int, frame: FrameType | None) -> None:
    raise TimeoutError("Predeclared execution budget exhausted; no outcome-based retry")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, default=Path("benchmarks/astra-v4-diagnosis/plan.json")
    )
    parser.add_argument("--out", type=Path, default=Path("artifacts/v4-formal"))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if sys.platform != "linux" or environment()["machine"] != "x86_64":
        raise RuntimeError("This control requires Linux x86_64")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("This control requires Python 3.12")
    if len(plan["openings"]) != 10 or len({r["fen"] for r in plan["openings"]}) != 10:
        raise RuntimeError("Expected ten distinct fixed opening positions")
    candidate, baseline = ROOT / "baselines/online_v4", ROOT / "baselines/online_v3"
    for directory, key in ((candidate, "candidate_sha256"), (baseline, "opponent_sha256")):
        if sha256(directory / "agent.py") != plan[key]:
            raise RuntimeError("Frozen source mismatch")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    if (out / "formal.json").exists():
        raise RuntimeError("Refusing to overwrite an earlier result or rerun in its directory")
    (out / "plan.json").write_bytes(args.plan.read_bytes())
    (out / "environment.json").write_text(json.dumps(environment(), indent=2) + "\n")
    report: dict[str, Any] = {
        "plan_sha256": sha256(args.plan),
        "started_utc": datetime.now(UTC).isoformat(),
        "candidate_sha256": plan["candidate_sha256"],
        "opponent_sha256": plan["opponent_sha256"],
        "requested_games": 20,
        "status": "running",
        "games": [],
    }
    signal.signal(signal.SIGTERM, stop_on_budget)
    try:
        for opening in plan["openings"]:
            for as_white in (True, False):
                index = len(report["games"]) + 1
                for directory, key in (
                    (candidate, "candidate_sha256"),
                    (baseline, "opponent_sha256"),
                ):
                    if sha256(directory / "agent.py") != plan[key]:
                        raise RuntimeError("Frozen source changed mid-batch")
                white_path, black_path = (
                    (candidate, baseline) if as_white else (baseline, candidate)
                )
                trace = out / f"game-{index:02d}.jsonl"
                white = RecordedAgent(white_path, trace, "white")
                black = RecordedAgent(black_path, trace, "black")
                started = time.monotonic()
                outcome = play_match(
                    white, black, 120_000, 500, start_fen=opening["fen"], ply_cap=600
                )
                game = chess.pgn.read_game(io.StringIO(outcome.pgn))
                assert game is not None and not game.errors
                game.headers.update(
                    {
                        "White": "v4" if as_white else "v3",
                        "Black": "v3" if as_white else "v4",
                        "Opening": opening["name"],
                        "Round": str(index),
                    }
                )
                board = game.board()
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
                    "elapsed_s": time.monotonic() - started,
                    "white_stderr": white.stderr_tail,
                    "black_stderr": black.stderr_tail,
                }
                report["games"].append(row)
                (out / f"game-{index:02d}.pgn").write_text(str(game) + "\n")
                (out / "formal.json").write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(row), flush=True)
        report["status"] = "completed"
    except Exception as error:
        report.update({"status": "incomplete", "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
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
        report["adjudications"] = sum(r["termination"] == "adjudication" for r in rows)
        (out / "formal.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "games"}), flush=True)


if __name__ == "__main__":
    main()

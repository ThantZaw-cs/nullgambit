"""Infrastructure recovery preserves logical outcomes and every interrupted attempt."""

import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chess
import chess.pgn

from tools.online_review import sha256
from tools.summarize_v8_matches import ROOT, summarize
from tools.v8_match import audit_retained_attempt, checkpoint, prepare_resume


class ResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        self.plan: dict[str, Any] = {
            "requested_games": 40,
            "execution_limit_s": 2400,
            "candidate_sha256": "candidate",
            "opponent_sha256": "v7",
            "openings": [
                {"name": f"opening-{i}", "fen": "7k/8/8/8/8/8/8/K7 w - - 0 1"}
                for i in range(20)
            ],
        }
        checkpoint(self.out / "plan.json", self.plan)

    def row(self, index: int, result: str, termination: str) -> dict[str, Any]:
        opening = self.plan["openings"][(index - 1) // 2]
        return {
            "index": index, "opening": opening["name"], "fen": opening["fen"],
            "candidate_white": index % 2 == 1, "result": result, "termination": termination,
        }

    def report(self, index: int = 2) -> dict[str, Any]:
        rows = [self.row(i, "black", "checkmate") for i in range(1, index)]
        rows.append(self.row(index, "void", "infrastructure_interruption"))
        report: dict[str, Any] = {
            "status": "incomplete", "plan_sha256": sha256(self.out / "plan.json"),
            "candidate_sha256": "candidate", "opponent_sha256": "v7",
            "execution_elapsed_s": 2400.25, "actual_games": index, "games": rows,
        }
        checkpoint(self.out / "results.json", report)
        checkpoint(self.out / f"game-{index:02d}.result.json", rows[-1])
        (self.out / f"game-{index:02d}.pgn").write_text('[Result "*"]\n\n*\n')
        (self.out / f"game-{index:02d}.jsonl").write_text('{"event":"init","elapsed_s":2}\n')
        return report

    def resume(self, report: dict[str, Any], **kwargs: Any) -> None:
        prepare_resume(
            self.out, report, self.plan, resume_infrastructure=True, extra_execution_s=600,
            **kwargs,
        )

    def test_archive_exact_bytes_keep_loss_and_elapsed(self) -> None:
        report = self.report()
        prior = {p.name: p.read_bytes() for p in self.out.iterdir()}
        self.resume(report)
        self.assertEqual(report["games"], [self.row(1, "black", "checkmate")])
        self.assertEqual(report["execution_elapsed_s"], 2400.25)
        self.assertEqual(report["extra_execution_s"], 600)
        reference = report["retained_infrastructure_attempts"][0]
        archive = self.out / reference["directory"]
        for name, data in prior.items():
            archived = "results-before-resume.json" if name == "results.json" else name
            self.assertEqual((archive / archived).read_bytes(), data)
        self.assertFalse((self.out / "game-02.jsonl").exists())
        audit_retained_attempt(self.out, reference)
        (archive / "game-02.pgn").write_text("tampered")
        with self.assertRaises(AssertionError):
            audit_retained_attempt(self.out, reference)

    def test_last_logical_game_can_resume(self) -> None:
        report = self.report(40)
        self.resume(report)
        self.assertEqual(len(report["games"]), 39)
        self.assertEqual(report["retained_infrastructure_attempts"][0]["logical_index"], 40)

    def test_completed_or_program_failed_game_never_retried(self) -> None:
        for result, reason in [
            ("white", "checkmate"), ("black", "checkmate"), ("draw", "threefold_repetition"),
            ("white", "flag"), ("black", "crash"), ("black", "init"),
            ("white", "illegal"), ("void", "both_failed"),
        ]:
            with self.subTest(result=result, reason=reason):
                report = self.report()
                report["games"][-1].update(result=result, termination=reason)
                checkpoint(self.out / "results.json", report)
                before = (self.out / "results.json").read_bytes()
                with self.assertRaises(AssertionError):
                    self.resume(report)
                self.assertEqual((self.out / "results.json").read_bytes(), before)

    def test_plan_hash_source_index_and_pending_mismatch_refused(self) -> None:
        for field in ("plan_sha256", "candidate_sha256", "opponent_sha256", "index", "pending"):
            with self.subTest(field=field):
                report = self.report()
                if field == "index":
                    report["games"][-1]["candidate_white"] = True
                elif field == "pending":
                    report["pending_game"] = {"index": 2}
                else:
                    report[field] = "wrong"
                with self.assertRaises(AssertionError):
                    self.resume(report)
                self.assertFalse((self.out / "retained-attempts").exists())

    def test_additional_allocation_is_cumulative_and_deadline_blocks(self) -> None:
        report = self.report()
        report["extra_execution_s"] = 200
        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(AssertionError, "deadline"):
            self.resume(report, deadline_utc=expired)
        self.assertFalse((self.out / "retained-attempts").exists())
        future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        self.resume(report, deadline_utc=future)
        self.assertEqual(report["extra_execution_s"], 800)
        self.assertEqual(report["execution_elapsed_s"], 2400.25)
        self.assertEqual(report["execution_deadline_utc"], future)

    def test_archive_recovery_is_idempotent_after_cleanup_interruption(self) -> None:
        report = self.report()
        self.resume(report)
        reference = report["retained_infrastructure_attempts"][0]
        archive = self.out / reference["directory"]
        # Simulate a crash after the report checkpoint, before canonical cleanup.
        for suffix in ("jsonl", "pgn", "result.json"):
            name = f"game-02.{suffix}"
            (self.out / name).write_bytes((archive / name).read_bytes())
        prepare_resume(
            self.out, report, self.plan, resume_infrastructure=True, extra_execution_s=0,
        )
        self.assertEqual(len(report["retained_infrastructure_attempts"]), 1)
        self.assertEqual(report["extra_execution_s"], 600)
        self.assertFalse((self.out / "game-02.jsonl").exists())
        # An already committed outcome for this ID can never be replaced by its old attempt.
        report["games"].append(self.row(2, "black", "checkmate"))
        checkpoint(self.out / "results.json", report)
        with self.assertRaises(AssertionError):
            prepare_resume(
                self.out, report, self.plan, resume_infrastructure=True, extra_execution_s=0,
            )

    def test_archive_committed_before_report_can_be_reused(self) -> None:
        report = self.report()
        original = copy.deepcopy(report)
        self.resume(report)
        reference = report["retained_infrastructure_attempts"][0]
        archive = self.out / reference["directory"]
        for suffix in ("jsonl", "pgn", "result.json"):
            name = f"game-02.{suffix}"
            (self.out / name).write_bytes((archive / name).read_bytes())
        checkpoint(self.out / "results.json", original)
        self.resume(original)
        self.assertEqual(len(original["retained_infrastructure_attempts"]), 1)
        self.assertEqual(len(original["games"]), 1)
        self.assertEqual(json.loads((self.out / "results.json").read_text())["actual_games"], 1)

    def test_summary_counts_final_logical_games_and_retained_void_separately(self) -> None:
        self.plan.update(
            candidate_directory="prototypes/search_core", candidate_name="candidate",
            candidate_sha256=sha256(ROOT / "prototypes/search_core/agent.py"),
            opponent_sha256=sha256(ROOT / "baselines/online_v7/agent.py"),
            base_ms=10000, increment_ms=100, ply_cap=600,
        )
        for index, opening in enumerate(self.plan["openings"]):
            board = chess.Board(None)
            board.set_piece_at(chess.A1, chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(chess.A4 + index, chess.Piece(chess.KING, chess.BLACK))
            opening["fen"] = board.fen()
        checkpoint(self.out / "plan.json", self.plan)
        report = self.report(40)
        report.update(
            candidate_sha256=self.plan["candidate_sha256"],
            opponent_sha256=self.plan["opponent_sha256"],
        )
        checkpoint(self.out / "results.json", report)
        self.resume(report)
        report["games"] = [self.row(i, "draw", "insufficient_material") for i in range(1, 41)]
        for row in report["games"]:
            index = row["index"]
            row.update(plies=0, total_plies=0)
            game = chess.pgn.Game.from_board(chess.Board(row["fen"]))
            game.headers.update(
                White="candidate" if row["candidate_white"] else "v7",
                Black="v7" if row["candidate_white"] else "candidate", Result="1/2-1/2",
            )
            (self.out / f"game-{index:02d}.pgn").write_text(str(game) + "\n")
            trace = [dict(event="init", side=side) for side in ("white", "black")]
            (self.out / f"game-{index:02d}.jsonl").write_text(
                "".join(json.dumps(entry) + "\n" for entry in trace)
            )
        timestamp = datetime.now(UTC).isoformat()
        report.update(
            status="completed", actual_games=40, requested_games=40, wins=0, draws=40,
            losses=0, voids=0, failures=0, adjudications=0, ply_cap_draws=0,
            started_utc=timestamp, finished_utc=timestamp,
        )
        checkpoint(self.out / "results.json", report)
        summary = summarize(self.out)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["draws"], 40)
        self.assertEqual(summary["voids"], 0)
        self.assertEqual(summary["retained_infrastructure_void_attempts"], 1)
        self.assertEqual(summary["infrastructure_interruptions"], 1)
        self.assertEqual(summary["raw_referee_score"], 0.5)


if __name__ == "__main__":
    unittest.main()

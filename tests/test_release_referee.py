"""Rule changes are explicit; historical material adjudication is never reused."""

import io
import unittest
from typing import Any

import chess
import chess.pgn

from harness.sandbox import Agent, AgentFailure
from tools.release_referee import play_match


class ScriptedAgent(Agent):
    def __init__(self, moves: tuple[str, ...] = (), failure: str | None = None) -> None:
        super().__init__([])
        self.moves = iter(moves)
        self.failure = failure
        self.stopped = False
        self.received: list[str] = []

    def start(self, init_budget_s: float) -> None:
        assert init_budget_s == 90
        if self.failure == "init":
            raise AgentFailure("init")

    def move(self, fen: str, time_left_ms: int) -> str:
        self.received.append(fen)
        if self.failure:
            raise AgentFailure(self.failure)
        return next(self.moves)

    def stop(self) -> None:
        self.stopped = True


class ReleaseRefereeTests(unittest.TestCase):
    def test_cap_draw_counts_opening_plies_despite_material_imbalance(self) -> None:
        fen = "7k/8/8/8/8/8/Q7/K7 w - - 0 300"
        white, black = ScriptedAgent(("a2a3",)), ScriptedAgent(("h8g8",))
        records: list[dict[str, Any]] = []
        result = play_match(white, black, 1000, 500, start_fen=fen, record=records.append)
        self.assertEqual((result.result, result.termination), ("draw", "ply_cap_draw"))
        game = chess.pgn.read_game(io.StringIO(result.pgn))
        assert game is not None
        self.assertEqual(game.board().fen(), fen)
        self.assertEqual(len(list(game.mainline_moves())), 2)
        self.assertEqual(game.end().board().ply(), 600)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["total_plies"], 600)
        for row in records:
            self.assertAlmostEqual(row["after_ms"], 1500 - row["charged_ms"])
        self.assertTrue(white.stopped and black.stopped)

    def test_mate_precedes_cap(self) -> None:
        result = play_match(ScriptedAgent(("g6g7",)), ScriptedAgent(), 1000, 0,
                            start_fen="7k/8/5KQ1/8/8/8/8/8 w - - 0 300", ply_cap=599)
        self.assertEqual((result.result, result.termination), ("white", "checkmate"))

    def test_observable_fifty_move_history_begins_at_opening(self) -> None:
        fen = "7k/8/8/8/8/8/Q7/K7 w - - 100 1"
        white = ScriptedAgent(("a2a3",))
        result = play_match(white, ScriptedAgent(), 1000, 0, start_fen=fen, ply_cap=1)
        self.assertEqual(result.termination, "ply_cap_draw")
        self.assertEqual(white.received, [fen])

    def test_actual_repetition_is_preserved(self) -> None:
        result = play_match(ScriptedAgent(("g1f3", "f3g1") * 2),
                            ScriptedAgent(("g8f6", "f6g8") * 2), 1000, 500)
        self.assertEqual((result.result, result.termination), ("draw", "threefold_repetition"))

    def test_both_init_failures_are_void_without_retry(self) -> None:
        white, black = ScriptedAgent(failure="init"), ScriptedAgent(failure="init")
        result = play_match(white, black, 1000, 0)
        self.assertEqual((result.result, result.termination), ("void", "both_failed"))
        self.assertTrue(white.stopped and black.stopped)

    def test_flag_draw_when_opponent_cannot_mate(self) -> None:
        result = play_match(ScriptedAgent(failure="flag"), ScriptedAgent(), 1000, 0,
                            start_fen="7k/8/8/8/8/8/Q7/K7 w - - 0 1")
        self.assertEqual((result.result, result.termination), ("draw", "flag"))

    def test_illegal_move_loses_and_stops_processes(self) -> None:
        white, black = ScriptedAgent(("e2e5",)), ScriptedAgent()
        result = play_match(white, black, 1000, 0)
        self.assertEqual((result.result, result.termination), ("black", "illegal"))
        self.assertTrue(white.stopped and black.stopped)

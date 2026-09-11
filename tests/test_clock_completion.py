"""Focused safety and OFF controls for completion-aware time allocation."""

import ast
import contextlib
import io
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from baselines.online_v7 import agent as baseline
from prototypes.clock_completion import agent as candidate


class ClockCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        candidate.USE_COMPLETION_TIME = True
        candidate._previous_board = None
        candidate._diagnostic_bytes = 7000

    def tearDown(self) -> None:
        candidate.USE_COMPLETION_TIME = True
        candidate._previous_board = None

    def test_search_core_unchanged(self) -> None:
        def functions(path: str) -> dict[str, str]:
            return {n.name: ast.dump(n) for n in ast.parse(Path(path).read_text()).body
                    if isinstance(n, ast.FunctionDef)}
        old, new = functions(baseline.__file__), functions(candidate.__file__)
        for name, body in old.items():
            if name not in {"get_move", "timed_search"}:
                self.assertEqual(body, new[name], name)
        old_get = ast.parse(Path(baseline.__file__).read_text())
        legacy = ast.parse(Path(candidate.__file__).read_text())
        a = next(n for n in old_get.body if isinstance(n, ast.FunctionDef)
                 and n.name == "get_move")
        b = next(n for n in legacy.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_legacy_get_move")
        b.name = a.name
        self.assertEqual(ast.dump(a), ast.dump(b))

    def test_safe_budgets_and_increment(self) -> None:
        board = chess.Board()
        for remaining in [0, .001, .01, .1, .5, 1, 3, 4, 10, 40, 70, 120, 300]:
            soft, hard = candidate._time_budgets(board, remaining, 20)
            reserve = max(.01, min(.25, remaining * .15))
            self.assertTrue(0 <= soft <= hard <= max(0, remaining - reserve))
            self.assertLessEqual(hard, 8)
        self.assertGreater(candidate._time_budgets(board, 70, 40)[1], 2.5)
        self.assertLess(candidate._time_budgets(board, 10, 20)[1], 2.5)

    def test_forced_move_returns_without_search(self) -> None:
        board = chess.Board("7k/8/5K1Q/8/8/8/8/8 b - - 0 1")
        self.assertEqual(board.legal_moves.count(), 1)
        with patch.object(candidate, "timed_search", side_effect=AssertionError("searched")):
            move = candidate.get_move(board.fen(), 120000)
        board.push_uci(move)
        assert candidate._previous_board is not None
        self.assertEqual(candidate._previous_board.fen(), board.fen())
        self.assertEqual(candidate.LAST_SEARCH_DEPTH, 0)

    def test_low_clock_keeps_repetition_history(self) -> None:
        board = chess.Board()
        for uci in ["g1f3", "g8f6", "f3g1", "f6g8"]:
            board.push_uci(uci)
        previous = board.copy(stack=True)
        previous.pop()
        candidate._previous_board = previous
        move = candidate.get_move(board.fen(), 1)
        self.assertEqual(candidate._previous_board.move_stack,
                         [*board.move_stack, chess.Move.from_uci(move)])

    def test_interruption_uses_last_completed_answer(self) -> None:
        board = chess.Board()
        moves = list(board.legal_moves)
        encoded = [candidate.encode_move(m.from_square, m.to_square) for m in moves[:2]]

        def root(*args: object) -> tuple[int, int]:
            depth = args[2]
            counters = args[4]
            counters[0] = 10  # type: ignore[index]
            if depth == 1:
                return encoded[1], 42
            counters[1] = 1  # type: ignore[index]
            return encoded[0], 9999

        with patch.object(candidate, "compiled_root_search", side_effect=root):
            move, depth, nodes = candidate.timed_search(board, .05, .01)
        self.assertEqual(move, moves[1].uci())
        self.assertEqual((depth, nodes, candidate.LAST_SEARCH_SCORE), (1, 20, 42))

    def test_off_control_fixed_search(self) -> None:
        candidate.USE_COMPLETION_TIME = False
        positions = [chess.Board(), chess.Board("8/k1P5/2K5/8/8/8/8/8 w - - 0 1"),
                     chess.Board("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1")]
        for board in positions:
            self.assertEqual(candidate.fixed_score(board, 3), baseline.fixed_score(board, 3))
        with patch.object(candidate, "_legacy_get_move", return_value="e2e4") as mocked:
            self.assertEqual(candidate.get_move(chess.STARTING_FEN, 1000), "e2e4")
            mocked.assert_called_once_with(chess.STARTING_FEN, 1000)

    def test_true_entry_low_clock_and_timeout_restore(self) -> None:
        for ms in [50, 100, 500, 1000, 3000]:
            board = chess.Board()
            start = time.monotonic()
            move = candidate.get_move(board.fen(), ms)
            elapsed = time.monotonic() - start
            self.assertIn(chess.Move.from_uci(move), board.legal_moves)
            self.assertLess(elapsed, ms / 1000)
            board.push_uci(move)
            assert candidate._previous_board is not None
            self.assertEqual(candidate._previous_board.fen(), board.fen())
            if ms >= 500:
                self.assertGreater(candidate.LAST_SEARCH_DEPTH, 0)
        source = chess.Board()
        before = source.fen(), source.move_stack.copy()
        candidate.timed_search(source, 0, 0)
        self.assertEqual((source.fen(), source.move_stack), before)

    def test_logging_bounded(self) -> None:
        candidate._diagnostic_bytes = 6980
        with contextlib.redirect_stderr(io.StringIO()) as stream:
            candidate.get_move(chess.STARTING_FEN, 1)
        self.assertLessEqual(candidate._diagnostic_bytes, 7000)
        self.assertLessEqual(len(stream.getvalue()), 20)


if __name__ == "__main__":
    unittest.main()

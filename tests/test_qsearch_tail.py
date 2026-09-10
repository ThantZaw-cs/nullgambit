"""Tactical completeness and search equivalence for the isolated quiet-tail exit."""

import ast
import hashlib
import random
import time
import unittest
from pathlib import Path
from typing import Any

import chess
import numpy as np

from baselines.online_v4 import agent as v4
from prototypes.qsearch_tail import agent as candidate
from tools.qsearch_bench import fixed, sources

SPECIAL = (
    "7k/8/8/3pP3/8/8/8/K7 w - d6 0 1",  # Legal EP.
    "k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",  # Pinned EP is illegal.
    "7k/P7/6K1/8/8/8/8/8 w - - 0 1",  # All four quiet promotions.
    "1r5k/P7/8/8/8/8/8/4K3 w - - 0 1",  # Four capture promotions too.
    "8/k1P5/2K5/8/8/8/8/8 w - - 0 1",  # Queen promotion stalemates.
    "4r2k/2P5/8/8/8/8/8/4K3 w - - 0 1",  # Quiet check evasions.
    "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1",  # Mate precedes 50-move draw.
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # Stalemate.
    "7k/8/8/8/8/8/Q7/K7 w - - 100 1",
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
)


def qscore(module: Any, source: chess.Board, alpha: int = -101000,
           beta: int = 101000, ply: int = 0) -> tuple[int, list[int]]:
    board, state = module.from_chess(source)
    original = board.copy(), state.copy()
    history = np.zeros(256, dtype=np.uint64)
    length = module._seed_history(source, history)
    prefix = history[:length].copy()
    counts = np.zeros(4, dtype=np.int64)
    score = module._quiescence(
        board, state, alpha, beta, ply, 4, time.monotonic() + 10,
        counts, history, length, np.zeros(module.TT_LIMIT, dtype=np.uint64),
        np.full(module.TT_LIMIT, -1, dtype=np.int64),
    )
    assert not counts[1]
    assert np.array_equal(board, original[0]) and np.array_equal(state, original[1])
    assert np.array_equal(history[:length], prefix)
    return int(score), counts.tolist()


class QsearchTailTests(unittest.TestCase):
    def test_only_quiescence_loop_exit_changes(self) -> None:
        old = Path(v4.__file__).read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         "7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4")
        before, after = ast.parse(old), ast.parse(Path(candidate.__file__).read_bytes())
        for tree, expected_exit in ((before, ast.Continue), (after, ast.Break)):
            for function in tree.body:
                if isinstance(function, ast.FunctionDef) and function.name == "_quiescence":
                    loop = next(n for n in function.body if isinstance(n, ast.For)
                                and isinstance(n.iter, ast.Call)
                                and ast.unparse(n.iter) == "range(count)")
                    condition = next(n for n in loop.body if isinstance(n, ast.If))
                    self.assertEqual(ast.unparse(condition.test),
                                     "not in_check and board[target] == 0 and "
                                     "(not move & (EP_FLAG | 7 << 12))")
                    self.assertEqual(len(condition.body), 1)
                    self.assertIsInstance(condition.body[0], expected_exit)
                    condition.body = [ast.Pass()]
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_legal_and_tactical_sets_and_priority_invariant(self) -> None:
        rng = random.Random(20260910)
        samples = [chess.Board(fen) for fen in SPECIAL]
        samples += [b.mirror() for b in samples]
        cursor = chess.Board()
        for _ in range(300):
            if cursor.is_game_over() or len(cursor.move_stack) >= 100:
                cursor = chess.Board()
            samples.append(cursor.copy(stack=True))
            cursor.push(rng.choice(list(cursor.legal_moves)))
        for source in samples:
            expected = {m.uci() for m in source.legal_moves}
            self.assertEqual(candidate.legal_uci(source), expected)
            board, state = candidate.from_chess(source)
            moves = np.empty(256, dtype=np.int64)
            count = candidate.compiled_legal_moves(board, state, moves)
            seen_quiet = False
            searched = set()
            for index in range(count):
                encoded = candidate._pick_ordered(board, moves, index, count)
                move = chess.Move.from_uci(candidate.move_to_uci(encoded))
                tactical = source.is_capture(move) or bool(move.promotion)
                if tactical:
                    self.assertFalse(seen_quiet, source.fen())
                else:
                    seen_quiet = True
                if source.is_check() or tactical:
                    searched.add(move.uci())
            self.assertEqual(searched, {m.uci() for m in source.legal_moves
                                       if source.is_check() or source.is_capture(m) or m.promotion})

    def test_full_and_narrow_quiescence_windows_preserve_scores_nodes_and_bounds(self) -> None:
        boards = [b for _, b in sources()] + [chess.Board(fen) for fen in SPECIAL]
        for board in boards:
            exact, _ = qscore(v4, board)
            self.assertEqual(qscore(candidate, board), qscore(v4, board))
            for alpha, beta in ((exact - 1, exact + 1), (exact + 10, exact + 11),
                                (exact - 11, exact - 10)):
                result = qscore(candidate, board, alpha, beta)
                self.assertEqual(result, qscore(v4, board, alpha, beta))
                score = result[0]
                if score <= alpha:
                    self.assertGreaterEqual(score, exact)  # Upper bound.
                elif score >= beta:
                    self.assertLessEqual(score, exact)  # Lower bound.
                else:
                    self.assertEqual(score, exact)

    def test_fixed_depth_moves_scores_and_nodes_unchanged(self) -> None:
        for name, source in sources():
            old, new = fixed(v4, source, 3), fixed(candidate, source, 3)
            for old_row, new_row in zip(old["iterations"], new["iterations"], strict=True):
                for key in ("move", "score", "nodes"):
                    self.assertEqual(old_row[key], new_row[key], (name, key))

    def test_repetition_terminal_max_ply_and_underpromotion(self) -> None:
        repeated = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
            repeated.push_uci(move)
        self.assertEqual(qscore(candidate, repeated)[0], 0)
        for fen, expected in ((SPECIAL[6], -100000), (SPECIAL[7], 0), (SPECIAL[8], 0)):
            self.assertEqual(qscore(candidate, chess.Board(fen))[0], expected)
        board = chess.Board(SPECIAL[4])
        self.assertGreater(qscore(candidate, board)[0], 400)
        self.assertEqual(qscore(candidate, board, ply=63), qscore(v4, board, ply=63))

    def test_nested_timeout_restores_board_state_and_history(self) -> None:
        source = sources()[0][1]
        for module in (v4, candidate):
            board, state = module.from_chess(source)
            original = board.copy(), state.copy()
            history = np.zeros(256, dtype=np.uint64)
            length = module._seed_history(source, history)
            prefix = history[:length].copy()
            counts = np.zeros(4, dtype=np.int64)
            module.compiled_root_search(
                board, state, 20, time.monotonic() - 1, counts, -1, history, length,
                np.zeros(module.TT_LIMIT, dtype=np.uint64),
                np.full(module.TT_LIMIT, -1, dtype=np.int64),
            )
            self.assertEqual(counts[1], 1)
            self.assertEqual(counts[0], 1024)
            np.testing.assert_array_equal(board, original[0])
            np.testing.assert_array_equal(state, original[1])
            np.testing.assert_array_equal(history[:length], prefix)


if __name__ == "__main__":
    unittest.main()

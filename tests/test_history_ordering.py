"""The ordering experiment must preserve minimax and special-move semantics."""

import unittest

import chess
import numpy as np

from baselines.online_v3 import agent as online_v3
from prototypes.numba_kernel import agent as candidate
from tools.online_review import search
from tools.positions import positions


class HistoryOrderingTests(unittest.TestCase):
    def test_online_development_fork_is_visible_beyond_shallow_search(self) -> None:
        # Round 54: 27.h3 allows ...Nc3, attacking Qb1 and Ba2. The previous
        # move was a capture, so the FEN's zero halfmove clock contains all
        # repetition context relevant to this search.
        board = chess.Board("r5k1/r3bppp/3p4/1p1npP2/1q6/1P2R3/B2N1P1P/RQB3K1 w - - 0 27")
        result = search(candidate, board, 30.0, 6)
        self.assertEqual(result["depth"], 6)
        self.assertEqual(result["move"], "d2f1")
        board.push_uci("h2h3")
        recorded_score = -candidate.fixed_score(board, 5)
        self.assertGreater(result["score_cp"] - recorded_score, 100)

    def test_fixed_depth_scores_match_frozen_online_engine(self) -> None:
        for name, fen in positions():
            board = chess.Board(fen)
            # Keep a real, nonempty repetition history in this differential check.
            for _ in range(2):
                board.push(next(iter(board.legal_moves)))
            with self.subTest(name=name):
                before = board.fen(), board.move_stack.copy()
                self.assertEqual(candidate.fixed_score(board, 3), online_v3.fixed_score(board, 3))
                self.assertEqual((board.fen(), board.move_stack), before)

    def test_quiet_history_is_separate_for_each_side(self) -> None:
        for color in (chess.WHITE, chess.BLACK):
            source = chess.Board()
            source.turn = color
            board, state = candidate.from_chess(source)
            moves = np.empty(256, dtype=np.int64)
            count = candidate.compiled_legal_moves(board, state, moves)
            original = moves.copy()
            scores = np.zeros((2, 64, 64), dtype=np.int64)
            wanted = chess.Move.from_uci("g1f3" if color else "g8f6")
            scores[int(color), wanted.from_square, wanted.to_square] = 100
            chosen = candidate._pick_search_ordered(board, state, moves, 0, count, scores)
            self.assertEqual(candidate.move_to_uci(chosen), wanted.uci())
            scores[int(color)] = 0
            scores[int(not color), wanted.from_square, wanted.to_square] = 100
            moves[:] = original
            chosen = candidate._pick_search_ordered(board, state, moves, 0, count, scores)
            # Other side's values cannot affect this side's priorities.
            self.assertEqual(chosen, original[0])
            self.assertEqual(scores[int(color)].sum(), 0)

    def test_tactical_moves_precede_even_saturated_quiet_history(self) -> None:
        cases = (
            ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", "e5d6"),
            ("7k/P7/6K1/8/8/8/8/8 w - - 0 1", "a7a8q"),
            ("7k/8/8/3p4/4P3/8/8/K7 w - - 0 1", "e4d5"),
        )
        for fen, expected in cases:
            with self.subTest(fen=fen):
                board, state = candidate.from_chess(chess.Board(fen))
                moves = np.empty(256, dtype=np.int64)
                count = candidate.compiled_legal_moves(board, state, moves)
                scores = np.full((2, 64, 64), 16_384, dtype=np.int64)
                chosen = candidate._pick_search_ordered(board, state, moves, 0, count, scores)
                self.assertEqual(candidate.move_to_uci(chosen), expected)


if __name__ == "__main__":
    unittest.main()

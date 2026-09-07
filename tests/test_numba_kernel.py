"""Correctness gates for the isolated compiled move-generation prototype."""

import random
import time
import unittest
from pathlib import Path

import chess
import numpy as np

from harness.rules import INIT_BUDGET_S
from harness.sandbox import local
from prototypes.numba_kernel import agent as kernel


class NumbaKernelTests(unittest.TestCase):
    def assert_moves_match(self, board: chess.Board) -> None:
        self.assertEqual(
            kernel.legal_uci(board), {move.uci() for move in board.legal_moves}, board.fen()
        )

    def test_reference_perft(self) -> None:
        board = chess.Board()
        self.assertEqual(
            [kernel.perft(board, depth) for depth in range(1, 5)], [20, 400, 8902, 197281]
        )
        complex_position = chess.Board(
            "r3k2r/p1ppqpb1/bn2pnp1/2pP4/1p2P3/2N2N2/PPQBBPPP/R3K2R w KQkq - 0 1"
        )
        self.assertEqual(
            [kernel.perft(complex_position, depth) for depth in range(1, 4)],
            [45, 1947, 85877],
        )

    def test_special_and_terminal_positions(self) -> None:
        positions = (
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            "7k/8/8/3pP3/8/8/8/K7 w - d6 0 1",
            "7k/P7/6K1/8/8/8/8/8 w - - 0 1",
            "4r2k/8/8/8/8/8/8/4K3 w - - 0 1",
            "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
            "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
        )
        for fen in positions:
            with self.subTest(fen=fen):
                self.assert_moves_match(chess.Board(fen))

    def test_one_thousand_seeded_legal_positions(self) -> None:
        rng = random.Random(20260907)
        board = chess.Board()
        checked = 0
        while checked < 1000:
            if board.is_game_over() or len(board.move_stack) >= 160:
                board = chess.Board()
            self.assert_moves_match(board)
            checked += 1
            board.push(rng.choice(list(board.legal_moves)))

    def test_make_unmake_restores_every_state_field(self) -> None:
        rng = random.Random(917)
        source = chess.Board()
        for _ in range(300):
            if source.is_game_over():
                source = chess.Board()
            board, state = kernel.from_chess(source)
            original_board, original_state = board.copy(), state.copy()
            moves = np.empty(256, dtype=np.int64)
            count = kernel.compiled_legal_moves(board, state, moves)
            for move in moves[:count]:
                undo = np.empty(10, dtype=np.int64)
                kernel.compiled_make(board, state, int(move), undo)
                kernel.compiled_unmake(board, state, undo)
                np.testing.assert_array_equal(board, original_board)
                np.testing.assert_array_equal(state, original_state)
            source.push(rng.choice(list(source.legal_moves)))

    def test_timed_search_tactics_and_special_moves(self) -> None:
        cases = (
            ("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1", "mate"),
            ("3r2k1/3p4/8/8/8/8/8/3Q2K1 w - - 0 1", "poison"),
            ("7k/P7/6K1/8/8/8/8/8 w - - 0 1", "promotion"),
            ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", "en_passant"),
        )
        for fen, label in cases:
            with self.subTest(label=label):
                board = chess.Board(fen)
                move, depth, _ = kernel.timed_search(board, 0.25)
                self.assertIn(chess.Move.from_uci(move), board.legal_moves)
                self.assertGreater(depth, 0)
                if label == "mate":
                    board.push_uci(move)
                    self.assertTrue(board.is_checkmate())
                elif label == "poison":
                    self.assertNotEqual(move, "d1d7")
                elif label == "promotion":
                    self.assertEqual(chess.Move.from_uci(move).promotion, chess.QUEEN)
                else:
                    self.assertEqual(move, "e5d6")

    def test_deadline_returns_legal_fallback_and_restores_input(self) -> None:
        board = chess.Board()
        before = board.fen()
        started = time.monotonic()
        move, _, _ = kernel.timed_search(board, 0.05)
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertIn(chess.Move.from_uci(move), board.legal_moves)
        self.assertEqual(board.fen(), before)

    def test_draw_and_terminal_precedence(self) -> None:
        mate = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 100 1")
        self.assertEqual(kernel.fixed_score(mate, 1), -100_000)
        self.assertEqual(
            kernel.fixed_score(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), 1),
            0,
        )
        self.assertEqual(
            kernel.fixed_score(chess.Board("7k/8/8/8/8/8/B7/K7 w - - 0 1"), 2),
            0,
        )
        fifty = chess.Board("7k/8/8/8/8/8/Q7/K7 w - - 100 1")
        self.assertEqual(kernel.fixed_score(fifty, 2), 0)

    def test_seeded_threefold_history_is_a_draw(self) -> None:
        board = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
            board.push_uci(move)
        self.assertTrue(board.is_repetition(3))
        self.assertEqual(kernel.fixed_score(board, 2), 0)

    def test_repetition_hash_uses_only_legal_en_passant(self) -> None:
        unavailable = chess.Board()
        unavailable.push_uci("e2e4")
        without_ep = unavailable.copy(stack=False)
        without_ep.ep_square = None
        first = kernel.from_chess(unavailable)
        second = kernel.from_chess(without_ep)
        self.assertEqual(kernel._position_hash(*first), kernel._position_hash(*second))
        pinned = chess.Board("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        without_ep = pinned.copy(stack=False)
        without_ep.ep_square = None
        first = kernel.from_chess(pinned)
        second = kernel.from_chess(without_ep)
        self.assertEqual(kernel._position_hash(*first), kernel._position_hash(*second))
        legal = chess.Board("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1")
        without_ep = legal.copy(stack=False)
        without_ep.ep_square = None
        first = kernel.from_chess(legal)
        second = kernel.from_chess(without_ep)
        self.assertNotEqual(kernel._position_hash(*first), kernel._position_hash(*second))

    def test_real_entry_is_safe_at_low_clock_and_recovers_history(self) -> None:
        kernel._previous_board = None
        for clock in (1, 5, 10, 50, 100, 500):
            for _ in range(3):
                board = chess.Board()
                started = time.monotonic()
                move = chess.Move.from_uci(kernel.get_move(board.fen(), clock))
                elapsed = time.monotonic() - started
                self.assertIn(move, board.legal_moves)
                self.assertLess(elapsed, clock / 1000.0)
        previous = kernel._previous_board
        assert previous is not None
        incoming = previous.copy()
        incoming.push(next(iter(incoming.legal_moves)))
        restored = kernel._restore_history(incoming.fen())
        self.assertEqual(len(restored.move_stack), 2)

    def test_move_only_tt_is_bounded(self) -> None:
        self.assertEqual(kernel.TT_LIMIT, 65_536)

    def test_independent_runner_import_and_move(self) -> None:
        runner = local(Path("prototypes/numba_kernel"))
        try:
            runner.start(INIT_BUDGET_S)
            board = chess.Board()
            move = chess.Move.from_uci(runner.move(board.fen(), 500))
            self.assertIn(move, board.legal_moves)
        finally:
            runner.stop()


if __name__ == "__main__":
    unittest.main()

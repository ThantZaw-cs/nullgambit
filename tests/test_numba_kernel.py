"""Correctness gates for the isolated compiled move-generation prototype."""

import random
import time
import unittest
from itertools import pairwise
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

    def test_root_history_survives_children_and_detects_third_occurrence(self) -> None:
        board = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
        compiled_board, state = kernel.from_chess(board)
        original_board, original_state = compiled_board.copy(), state.copy()
        history = np.zeros(256, dtype=np.uint64)
        history_len = kernel._seed_history(board, history)
        prefix = history[:history_len].copy()
        root_key = kernel._position_hash(compiled_board, state)
        tt_keys = np.zeros(kernel.TT_LIMIT, dtype=np.uint64)
        tt_moves = np.full(kernel.TT_LIMIT, -1, dtype=np.int64)

        def encoded(position: chess.Board, uci: str) -> int:
            inner_board, inner_state = kernel.from_chess(position)
            moves = np.empty(256, dtype=np.int64)
            count = kernel.compiled_legal_moves(inner_board, inner_state, moves)
            return next(int(move) for move in moves[:count] if kernel.move_to_uci(int(move)) == uci)

        cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
        cursor = board.copy()
        preferred = encoded(cursor, cycle[0])
        for uci, reply in pairwise(cycle):
            cursor.push_uci(uci)
            inner_board, inner_state = kernel.from_chess(cursor)
            key = kernel._position_hash(inner_board, inner_state)
            index = int(key & np.uint64(kernel.TT_LIMIT - 1))
            tt_keys[index] = key
            tt_moves[index] = encoded(cursor, reply)
        initial_tt_keys = tt_keys.copy()
        initial_tt_moves = tt_moves.copy()

        first_result: tuple[int, int] | None = None
        deadlines = (time.monotonic() + 10, time.monotonic() + 10, time.monotonic() - 1)
        for run, deadline in enumerate(deadlines):
            tt_keys[:] = initial_tt_keys
            tt_moves[:] = initial_tt_moves
            counters = np.zeros(4, dtype=np.int64)
            result = kernel.compiled_root_search(
                compiled_board,
                state,
                4,
                deadline,
                counters,
                preferred,
                history,
                history_len,
                tt_keys,
                tt_moves,
            )
            np.testing.assert_array_equal(compiled_board, original_board)
            np.testing.assert_array_equal(state, original_state)
            np.testing.assert_array_equal(history[:history_len], prefix)
            self.assertEqual(history[history_len], root_key)
            if run == 0:
                first_result = result
                self.assertGreater(counters[3], 0)
            elif run == 1:
                self.assertEqual(result, first_result)
                self.assertGreater(counters[3], 0)
            else:
                self.assertEqual(counters[1], 1)

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

    def test_real_entry_searches_with_overhead_and_long_history(self) -> None:
        line = ("g1f3", "g8f6", "b1c3", "b8c6", "f3g1", "f6g8", "c3b1", "c6b8")
        complete = chess.Board()
        for uci in line:
            complete.push_uci(uci)
        previous = complete.copy()
        previous.pop()
        for clock in (700, 800, 1000, 2000):
            for _ in range(3):
                kernel._previous_board = previous.copy()
                started = time.monotonic()
                move = chess.Move.from_uci(kernel.get_move(complete.fen(), clock))
                elapsed = time.monotonic() - started
                self.assertIn(move, complete.legal_moves)
                self.assertGreater(kernel.LAST_SEARCH_DEPTH, 0)
                self.assertLess(elapsed, clock / 1000.0)

    def test_move_only_tt_is_bounded(self) -> None:
        self.assertEqual(kernel.TT_LIMIT, 65_536)

    def test_independent_runner_import_and_move(self) -> None:
        runner = local(Path("prototypes/numba_kernel"))
        try:
            runner.start(INIT_BUDGET_S)
            board = chess.Board(
                "r1bqk2r/2p1bppp/p1np1n2/1p2p3/4P3/1B3N2/PPPP1PPP/RNBQR1K1 w kq - 0 8"
            )
            for clock in (700, 800, 1000, 2000):
                started = time.monotonic()
                move = chess.Move.from_uci(runner.move(board.fen(), clock))
                self.assertLess(time.monotonic() - started, clock / 1000.0)
                self.assertIn(move, board.legal_moves)
                board.push(move)
                if not board.is_game_over():
                    board.push(next(iter(board.legal_moves)))
        finally:
            runner.stop()


if __name__ == "__main__":
    unittest.main()

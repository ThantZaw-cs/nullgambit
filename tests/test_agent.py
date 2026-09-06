"""Tactical and clock regressions; run with python -m unittest discover -s tests."""

import random
import time
import unittest
from unittest.mock import patch

import chess

import agent
from baselines.classical_v1 import agent as reference


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        agent._previous_board = None
        agent._transpositions.clear()

    def search(self, board: chess.Board, depth: int = 2) -> chess.Move:
        search = agent.Search(time.monotonic() + 10)
        before = board.fen()
        search.negamax(board, depth, -agent.INFINITY, agent.INFINITY, 0)
        self.assertEqual(board.fen(), before)
        return search.best_moves[agent._position_key(board)]

    def test_mate_in_one_for_both_colors(self) -> None:
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        for position in (board, board.mirror()):
            with self.subTest(fen=position.fen()):
                position.push(self.search(position))
                self.assertTrue(position.is_checkmate())

    def test_quiescence_rejects_a_poisoned_capture(self) -> None:
        board = chess.Board("3r2k1/3p4/8/8/8/8/8/3Q2K1 w - - 0 1")
        self.assertNotEqual(self.search(board, 1).uci(), "d1d7")

    def test_en_passant_wins_a_pawn(self) -> None:
        board = chess.Board("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1")
        self.assertEqual(self.search(board).uci(), "e5d6")

    def test_promotion(self) -> None:
        board = chess.Board("7k/P7/6K1/8/8/8/8/8 w - - 0 1")
        move = self.search(board)
        self.assertEqual(move.from_square, chess.A7)
        self.assertEqual(move.promotion, chess.QUEEN)

    def test_castling_positions_remain_legal(self) -> None:
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        move = chess.Move.from_uci(agent.get_move(board.fen(), 1_000))
        self.assertIn(move, board.legal_moves)
        board.push(move)
        saved = agent._previous_board
        assert saved is not None
        self.assertEqual(saved.fen(), board.fen())

    def test_quiescence_searches_quiet_check_evasions(self) -> None:
        board = chess.Board("4r2k/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertTrue(board.is_check())
        self.assertTrue(all(not board.is_capture(move) for move in board.legal_moves))
        search = agent.Search(time.monotonic() + 10)
        search.quiescence(board, -agent.INFINITY, agent.INFINITY, 0, 0)
        self.assertGreater(search.nodes, 1)

    def test_checkmate_precedes_fifty_move_draw(self) -> None:
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 100 1")
        search = agent.Search(time.monotonic() + 10)
        self.assertEqual(search.negamax(board, 1, -agent.INFINITY, agent.INFINITY, 0), -agent.MATE)

    def test_stalemate_is_zero(self) -> None:
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        search = agent.Search(time.monotonic() + 10)
        self.assertEqual(search.quiescence(board, -agent.INFINITY, agent.INFINITY, 0, 4), 0)

    def test_timeout_restores_the_board(self) -> None:
        board = chess.Board()
        board.push_uci("e2e4")
        before, stack = board.fen(), board.move_stack.copy()
        search = agent.Search(time.monotonic() + 10)
        calls = 0

        def interrupt_search() -> None:
            nonlocal calls
            calls += 1
            if calls == 40:
                raise agent.SearchTimeout

        with patch.object(search, "check_time", side_effect=interrupt_search):
            move = search.choose(board, next(iter(board.legal_moves)))
        self.assertEqual(calls, 40)
        self.assertEqual(board.fen(), before)
        self.assertEqual(board.move_stack, stack)
        self.assertIn(move, board.legal_moves)
        self.assertEqual(search.undo_history, [])

    def test_expired_budget_returns_immediately(self) -> None:
        board = chess.Board()
        for clock in (0, 1, 5, 10):
            with self.subTest(clock=clock), patch.object(agent.Search, "choose") as choose:
                started = time.monotonic()
                move = chess.Move.from_uci(agent.get_move(board.fen(), clock))
                self.assertLess(time.monotonic() - started, 0.1)
                self.assertIn(move, board.legal_moves)
                choose.assert_not_called()

    def test_history_recovers_threefold_repetition(self) -> None:
        board = chess.Board()
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"):
            board.push_uci(uci)
        agent._previous_board = board.copy()
        board.push_uci("f6g8")
        restored = agent._restore_history(board.fen())
        self.assertEqual(restored.move_stack, board.move_stack)
        self.assertTrue(restored.is_repetition(3))

    def test_unrelated_fen_discards_history(self) -> None:
        agent._previous_board = chess.Board()
        agent._previous_board.push_uci("e2e4")
        board = agent._restore_history(chess.STARTING_FEN)
        self.assertEqual(board.fen(), chess.STARTING_FEN)
        self.assertEqual(board.move_stack, [])

    def test_color_symmetric_evaluation(self) -> None:
        board = chess.Board()
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"):
            board.push_uci(uci)
        self.assertLessEqual(abs(agent.evaluate(board) - agent.evaluate(board.mirror())), 1)

    def test_compiled_evaluation_matches_reference(self) -> None:
        rng = random.Random(73)
        board = chess.Board()
        for index in range(300):
            if index % 75 == 0 or board.is_game_over():
                board = chess.Board()
            base = agent._compiled_evaluate(
                board.pawns,
                board.knights,
                board.bishops,
                board.rooks,
                board.queens,
                board.kings,
                board.occupied_co[chess.WHITE],
                board.occupied_co[chess.BLACK],
            )
            self.assertEqual(base if board.turn else -base, reference.evaluate(board), board.fen())
            board.push(rng.choice(list(board.legal_moves)))

    def test_principal_variation_search_matches_full_window_search(self) -> None:
        board = chess.Board()
        for move in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
            board.push_san(move)
        for position in (chess.Board(), board, board.mirror()):
            with patch.object(reference, "evaluate", agent.evaluate):
                expected = reference.Search(time.monotonic() + 10).negamax(
                    position, 2, -agent.INFINITY, agent.INFINITY, 0
                )
            actual = agent.Search(time.monotonic() + 10).negamax(
                position, 2, -agent.INFINITY, agent.INFINITY, 0
            )
            self.assertEqual(actual, expected, position.fen())

    def test_score_cache_reuses_completed_search(self) -> None:
        board = chess.Board()
        search = agent.Search(time.monotonic() + 10)
        expected = search.negamax(board, 2, -agent.INFINITY, agent.INFINITY, 0)
        nodes = search.nodes
        actual = search.negamax(board, 2, -agent.INFINITY, agent.INFINITY, 0)
        self.assertEqual(actual, expected)
        self.assertEqual(search.nodes - nodes, 1)
        self.assertGreater(search.table_hits, 0)

    def test_score_cache_separates_fifty_move_clock(self) -> None:
        board = chess.Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1")
        search = agent.Search(time.monotonic() + 10)
        score = search.negamax(board, 1, -agent.INFINITY, agent.INFINITY, 0)
        self.assertGreater(score, 500)
        board.halfmove_clock = 99
        score = search.negamax(board, 1, -agent.INFINITY, agent.INFINITY, 0)
        self.assertEqual(score, 0)

    def test_score_cache_separates_repetition_history(self) -> None:
        board = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
        search = agent.Search(time.monotonic() + 10)
        search.prepare_history(board)
        repeated_key = search.score_key(board)
        search.prepare_history(chess.Board(board.fen()))
        self.assertNotEqual(search.score_key(board), repeated_key)

    def test_mate_cache_distance_is_relative_to_current_root(self) -> None:
        for score in (agent.MATE - 9, -agent.MATE + 9):
            stored = agent._store_mate(score, 4)
            self.assertEqual(agent._load_mate(stored, 4), score)
            expected = score + 2 if score > 0 else score - 2
            self.assertEqual(agent._load_mate(stored, 2), expected)

    def test_repetition_key_ignores_unavailable_en_passant(self) -> None:
        board = chess.Board()
        board.push_uci("e2e4")
        key = agent._position_key(board)
        board.ep_square = None
        self.assertEqual(agent._position_key(board), key)
        pinned = chess.Board("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        key = agent._position_key(pinned)
        pinned.ep_square = None
        self.assertEqual(agent._position_key(pinned), key)
        legal = chess.Board("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1")
        key = agent._position_key(legal)
        legal.ep_square = None
        self.assertNotEqual(agent._position_key(legal), key)

    def test_quiet_underpromotion_avoids_stalemate(self) -> None:
        board = chess.Board("8/k1P5/2K5/8/8/8/8/8 w - - 0 1")
        board.push_uci("c7c8q")
        self.assertTrue(board.is_stalemate())
        board.pop()
        search = agent.Search(time.monotonic() + 10)
        # Quiescence must consider the quiet rook promotion as well as the queen;
        # the full search may instead prefer a king move and promote next turn.
        score = search.quiescence(board, -agent.INFINITY, agent.INFINITY, 0, 4)
        self.assertGreater(score, 400)

    def test_capture_resets_and_restores_repetition_context(self) -> None:
        board = chess.Board("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1")
        search = agent.Search(time.monotonic() + 10)
        search.prepare_history(board)
        expected = search.repetitions.copy()
        before = board.fen()
        search.push(board, chess.Move.from_uci("e5d6"))
        self.assertEqual(sum(search.repetitions.values()), 1)
        search.pop(board)
        self.assertEqual(search.repetitions, expected)
        self.assertEqual(board.fen(), before)

    def test_table_has_a_fixed_entry_limit(self) -> None:
        search = agent.Search(time.monotonic() + 10)
        with patch.object(agent, "TABLE_LIMIT", 4):
            search.negamax(chess.Board(), 2, -agent.INFINITY, agent.INFINITY, 0)
        self.assertLessEqual(len(search.table), 4)


if __name__ == "__main__":
    unittest.main()

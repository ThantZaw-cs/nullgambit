"""Independent safety gates for score reuse and conservative selective search."""

import ast
import hashlib
import random
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import chess
import numpy as np

from prototypes.qsearch_tail import agent as v7
from prototypes.search_core import agent as candidate

V7_HASH = "aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d"
SPECIAL = (
    "7k/8/8/3pP3/8/8/8/K7 w - d6 0 1",
    "k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
    "7k/P7/6K1/8/8/8/8/8 w - - 0 1",
    "1r5k/P7/8/8/8/8/8/4K3 w - - 0 1",
    "8/k1P5/2K5/8/8/8/8/8 w - - 0 1",
    "4r2k/2P5/8/8/8/8/8/4K3 w - - 0 1",
    "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1",
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "7k/8/8/8/8/8/Q7/K7 w - - 100 1",
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
)


def scratch(source: chess.Board) -> tuple[Any, ...]:
    board, state = candidate.from_chess(source)
    history = np.zeros(256, dtype=np.uint64)
    length = candidate._seed_history(source, history)
    keys = np.zeros(candidate.TT_LIMIT, dtype=np.uint64)
    moves = np.full(candidate.TT_LIMIT, -1, dtype=np.int64)
    data, context = candidate.new_score_table()
    return board, state, history, length, keys, moves, data, context


def node(source: chess.Board, depth: int, *, alpha: int = -101000, beta: int = 101000,
         ply: int = 0, use_tt: bool = True, use_lmr: bool = False,
         state_tuple: tuple[Any, ...] | None = None,
         deadline: float | None = None) -> tuple[int, list[int], tuple[Any, ...]]:
    fields = scratch(source) if state_tuple is None else state_tuple
    board, state, history, length, keys, moves, data, context = fields
    before = board.copy(), state.copy(), history[:length].copy()
    counts = np.zeros(16, dtype=np.int64)
    score = candidate._negamax(
        board, state, depth, alpha, beta, ply,
        time.monotonic() + 15 if deadline is None else deadline,
        counts, history, length, keys, moves, np.zeros((2, 64, 64), dtype=np.int64),
        data, context, use_tt, use_lmr,
    )
    np.testing.assert_array_equal(board, before[0])
    np.testing.assert_array_equal(state, before[1])
    np.testing.assert_array_equal(history[:length], before[2])
    return int(score), counts.tolist(), fields


def iterative(module: Any, source: chess.Board, depth: int, *, use_tt: bool = False,
              use_lmr: bool = False) -> list[tuple[str, int, int]]:
    board, state, history, length, keys, moves, data, context = scratch(source)
    before = board.copy(), state.copy(), history[:length].copy()
    preferred = -1
    rows = []
    for current in range(1, depth + 1):
        counts = np.zeros(16, dtype=np.int64)
        args = (board, state, current, time.monotonic() + 20, counts, preferred,
                history, length, keys, moves)
        if module is candidate:
            best, score = module._root_search(*args, data, context, use_tt, use_lmr)
        else:
            best, score = module._root_search(*args)
        assert not counts[1]
        rows.append((module.move_to_uci(best), int(score), int(counts[0])))
        preferred = best
        np.testing.assert_array_equal(board, before[0])
        np.testing.assert_array_equal(state, before[1])
        np.testing.assert_array_equal(history[:length], before[2])
    return rows


class SearchCoreTests(unittest.TestCase):
    def test_frozen_v7_and_non_search_code_are_unchanged(self) -> None:
        old = Path(v7.__file__).read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(), V7_HASH)
        old_functions = {n.name: n for n in ast.parse(old).body
                         if isinstance(n, ast.FunctionDef)}
        new_functions = {n.name: n for n in ast.parse(Path(candidate.__file__).read_bytes()).body
                         if isinstance(n, ast.FunctionDef)}
        for name in ("_quiescence", "_evaluate", "_make", "_unmake", "_legal_moves",
                     "_pseudo_moves", "_position_hash", "_draw_by_history", "_seed_history",
                     "_restore_history", "get_move"):
            self.assertEqual(ast.dump(old_functions[name]), ast.dump(new_functions[name]), name)
        self.assertIn("prototypes/search_core", Path(candidate.__file__).as_posix())

    def test_special_moves_mirrors_and_complete_state_restoration(self) -> None:
        samples = [chess.Board(fen) for fen in SPECIAL]
        samples += [b.mirror() for b in samples]
        rng = random.Random(20260910)
        cursor = chess.Board()
        for _ in range(60):
            if cursor.is_game_over():
                cursor = chess.Board()
            samples.append(cursor.copy(stack=True))
            cursor.push(rng.choice(list(cursor.legal_moves)))
        for source in samples:
            self.assertEqual(candidate.legal_uci(source), {m.uci() for m in source.legal_moves})
            board, state = candidate.from_chess(source)
            before = board.copy(), state.copy()
            moves = np.empty(256, dtype=np.int64)
            count = candidate.compiled_legal_moves(board, state, moves)
            for move in moves[:count]:
                undo = np.empty(10, dtype=np.int64)
                candidate.compiled_make(board, state, int(move), undo)
                candidate.compiled_unmake(board, state, undo)
                np.testing.assert_array_equal(board, before[0])
                np.testing.assert_array_equal(state, before[1])
        for source in (chess.Board(SPECIAL[2]), chess.Board(SPECIAL[3])):
            promotions = {m.promotion for m in source.legal_moves if m.promotion}
            self.assertEqual(promotions, {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN})

    def test_both_switches_off_reproduce_v7_moves_scores_and_nodes(self) -> None:
        samples = [chess.Board(), chess.Board(SPECIAL[0]), chess.Board(SPECIAL[4]),
                   chess.Board(SPECIAL[5])]
        opening = chess.Board()
        for san in ("d4", "d5", "c4", "e6", "Nc3", "Nf6"):
            opening.push_san(san)
        samples.append(opening)
        for source in samples:
            self.assertEqual(iterative(candidate, source, 3), iterative(v7, source, 3))

    def test_history_context_preserves_multiplicity_but_ignores_order(self) -> None:
        first = np.array([13, 17, 13, 23], dtype=np.uint64)
        reordered = np.array([23, 13, 17, 13], dtype=np.uint64)
        different = np.array([13, 17, 23, 23], dtype=np.uint64)
        self.assertEqual(candidate._history_context(first, 4, 4),
                         candidate._history_context(reordered, 4, 4))
        self.assertNotEqual(candidate._history_context(first, 4, 4),
                            candidate._history_context(different, 4, 4))
        # XOR alone would erase both repeated pairs; multiplicity must survive.
        self.assertNotEqual(candidate._history_context(np.array([13, 13], dtype=np.uint64), 2, 2),
                            candidate._history_context(np.array([17, 17], dtype=np.uint64), 2, 2))
        padded = np.array([999, 998, 13, 17], dtype=np.uint64)
        short = np.array([13, 17], dtype=np.uint64)
        self.assertEqual(candidate._history_context(padded, 4, 2),
                         candidate._history_context(short, 2, 2))
        self.assertEqual(candidate._history_context(padded, 4, 0),
                         candidate._history_context(short, 0, 0))

    def test_mate_distance_round_trip_and_other_root_ply(self) -> None:
        for score in (-99997, -99800, -1200, 0, 700, 99800, 99997):
            for ply in (0, 1, 17, 62):
                stored = candidate._score_to_tt(score, ply)
                self.assertEqual(candidate._score_from_tt(stored, ply), score)
                if abs(score) < 99000:
                    self.assertEqual(stored, score)
        self.assertEqual(candidate._score_from_tt(candidate._score_to_tt(99990, 5), 8), 99987)
        self.assertEqual(candidate._score_from_tt(candidate._score_to_tt(-99990, 5), 8), -99987)

    def test_tt_depth_flags_history_halfmove_ply_configuration_and_collision(self) -> None:
        keys = np.zeros(candidate.TT_LIMIT, dtype=np.uint64)
        moves = np.full(candidate.TT_LIMIT, -1, dtype=np.int64)
        data, contexts = candidate.new_score_table()
        self.assertEqual(data.shape, (candidate.TT_LIMIT, 8))
        self.assertEqual(contexts.shape, (candidate.TT_LIMIT, 2))
        self.assertLess(data.nbytes + contexts.nbytes + keys.nbytes + moves.nbytes, 10_000_000)
        key = np.uint64(123456789)
        context = candidate._history_context(np.array([11, 23, 11], dtype=np.uint64), 3, 3)
        c1, c2, length = context

        def store(flag: int, score: int = 42) -> None:
            candidate._tt_store(key, 1234, 4, score, flag, 3, 3, length, c1, c2,
                                keys, moves, data, contexts, False)

        def probe(*, requested: int = 4, alpha: int = -100, beta: int = 100,
                  ply: int = 3, halfmove: int = 3, hlen: int = length,
                  first: Any = c1, second: Any = c2, lmr: bool = False,
                  lookup: Any = key) -> tuple[bool, int, bool]:
            hit, score, compatible = candidate._tt_probe(
                lookup, requested, alpha, beta, ply, halfmove, hlen, first, second,
                keys, data, contexts, lmr,
            )
            return bool(hit), int(score), bool(compatible)

        for flag in (1, 2, 3):
            store(flag)
            if flag == 1:
                self.assertEqual(probe(), (True, 42, True))
            else:
                self.assertFalse(probe()[0])
                self.assertTrue(probe()[2])
            self.assertTrue(probe(alpha=41, beta=42)[0] if flag in (1, 2)
                            else probe(alpha=42, beta=43)[0])
        store(1)
        self.assertFalse(probe(requested=5)[0])
        for changes in ({"ply": 2}, {"halfmove": 4}, {"hlen": length + 1},
                        {"first": np.uint64(int(c1) ^ 1)},
                        {"second": np.uint64(int(c2) ^ 1)}, {"lmr": True}):
            self.assertFalse(probe(**changes)[0], changes)
            self.assertFalse(probe(**changes)[2], changes)
        index = int(key & np.uint64(candidate.TT_LIMIT - 1))
        # A rejected score does not remove its useful move-ordering hint.
        self.assertEqual(int(moves[index]), 1234)
        collision = key + np.uint64(candidate.TT_LIMIT)
        candidate._tt_store(collision, 5678, 4, 77, 1, 3, 3, length, c1, c2,
                            keys, moves, data, contexts, False)
        self.assertFalse(probe()[0])
        self.assertTrue(probe(lookup=collision)[0])
        self.assertEqual(int(moves[index]), 5678)

    def test_tt_full_window_scores_and_narrow_window_bound_semantics(self) -> None:
        sources = [chess.Board(SPECIAL[0]), chess.Board(SPECIAL[4]), chess.Board(SPECIAL[5]),
                   chess.Board("3r2k1/3p4/8/8/8/8/8/3Q2K1 w - - 0 1"), chess.Board()]
        for source in sources:
            exact = node(source, 3, use_tt=False)[0]
            score, counts, fields = node(source, 3)
            self.assertFalse(counts[1])
            self.assertEqual(score, exact, source.fen())
            # The second identical request must really consume a compatible cached score.
            cached, second_counts, _ = node(source, 3, state_tuple=fields)
            self.assertEqual(cached, exact)
            self.assertLess(second_counts[0], counts[0])
            for alpha, beta in ((exact - 1, exact + 1), (exact + 10, exact + 11),
                                (exact - 11, exact - 10)):
                bounded, _, fields = node(source, 3, alpha=alpha, beta=beta)
                if bounded <= alpha:
                    self.assertGreaterEqual(bounded, exact)
                elif bounded >= beta:
                    self.assertLessEqual(bounded, exact)
                else:
                    self.assertEqual(bounded, exact)
                # Reusing a previous LOWER/UPPER must not turn it into an exact answer.
                self.assertEqual(node(source, 3, state_tuple=fields)[0], exact)

    def test_terminal_repetition_fifty_and_max_ply_precede_score_reuse(self) -> None:
        repeated = chess.Board()
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
            repeated.push_uci(uci)
        for source, expected in ((chess.Board(SPECIAL[6]), -100000),
                                 (chess.Board(SPECIAL[7]), 0),
                                 (chess.Board(SPECIAL[8]), 0), (repeated, 0)):
            for tt, lmr in ((False, False), (True, False), (False, True), (True, True)):
                self.assertEqual(node(source, 3, use_tt=tt, use_lmr=lmr)[0], expected)
        source = chess.Board()
        board, state = candidate.from_chess(source)
        expected = int(candidate._evaluate(board, int(state[0])))
        self.assertEqual(node(source, 8, ply=candidate.MAX_PLY - 1)[0], expected)
        # Terminal/qsearch leaves never populate the score table.
        _, _, fields = node(source, 0)
        self.assertFalse(np.any(fields[6][:, 2]))

    def test_incomplete_node_not_cached_and_nested_timeout_fully_unwinds(self) -> None:
        source = chess.Board()
        source.push_san("e4")
        source.push_san("e5")
        for tt, lmr in ((False, False), (True, False), (False, True), (True, True)):
            _, counts, fields = node(source, 20, use_tt=tt, use_lmr=lmr,
                                     deadline=time.monotonic() - 1)
            self.assertEqual(counts[1], 1)
            board, state, _, _, keys, _, data, _ = fields
            key = candidate._position_hash(board, state)
            index = int(key & np.uint64(candidate.TT_LIMIT - 1))
            self.assertFalse(keys[index] == key and data[index, 2] != 0)

    def test_lmr_eligibility_excludes_every_protected_move_class(self) -> None:
        self.assertTrue(candidate._can_reduce(3, 3, 0, 1, False, False, False))
        self.assertFalse(candidate._can_reduce(2, 3, 0, 1, False, False, False))
        for index in range(3):
            self.assertFalse(candidate._can_reduce(4, index, 0, 1, False, False, False))
        self.assertFalse(candidate._can_reduce(4, 3, -100, 100, False, False, False))
        for checked, tactical, checking in ((True, False, False), (False, True, False),
                                           (False, False, True)):
            self.assertFalse(candidate._can_reduce(4, 3, 0, 1, checked, tactical, checking))

    def test_lmr_reduced_fail_high_always_verifies_full_depth(self) -> None:
        source = chess.Board()
        board, state, history, length, keys, moves, data, contexts = scratch(source)
        before = board.copy(), state.copy(), history[:length].copy()
        counts = np.zeros(16, dtype=np.int64)
        original = candidate._negamax.py_func
        calls: list[tuple[int, int, int]] = []

        def fake_child(*args: Any) -> int:
            calls.append((int(args[2]), int(args[3]), int(args[4])))
            # First three moves fail low. Move four appears to beat beta at
            # reduced depth, but its mandatory full-depth verification fails low.
            return -12 if len(calls) == 4 else 0

        with patch.object(candidate, "_negamax", side_effect=fake_child):
            score = original(board, state, 4, 10, 11, 0, time.monotonic() + 2,
                             counts, history, length, keys, moves,
                             np.zeros((2, 64, 64), dtype=np.int64), data, contexts, False, True)
        self.assertEqual(score, 0)
        self.assertEqual(calls[:5], [(3, -11, -10)] * 3 + [(2, -11, -10), (3, -11, -10)])
        self.assertEqual(counts[10], 1)
        self.assertGreater(counts[9], 0)
        np.testing.assert_array_equal(board, before[0])
        np.testing.assert_array_equal(state, before[1])
        np.testing.assert_array_equal(history[:length], before[2])

    def test_pvs_still_researches_full_window_and_pv_moves_are_not_reduced(self) -> None:
        source = chess.Board()
        board, state, history, length, keys, moves, data, contexts = scratch(source)
        counts = np.zeros(16, dtype=np.int64)
        original = candidate._negamax.py_func
        calls: list[tuple[int, int, int]] = []

        def fake_child(*args: Any) -> int:
            calls.append((int(args[2]), int(args[3]), int(args[4])))
            return -20 if len(calls) in (2, 3) else 0

        with patch.object(candidate, "_negamax", side_effect=fake_child):
            score = original(board, state, 4, 10, 100, 0, time.monotonic() + 2,
                             counts, history, length, keys, moves,
                             np.zeros((2, 64, 64), dtype=np.int64), data, contexts, False, True)
        self.assertEqual(score, 20)
        self.assertEqual(calls[:3], [(3, -100, -10), (3, -11, -10), (3, -100, -10)])
        self.assertTrue(all(depth == 3 for depth, _, _ in calls))
        self.assertEqual(counts[9], 0)

    def test_lmr_real_move_classification_including_discovered_checks(self) -> None:
        positions = [chess.Board(fen) for fen in SPECIAL[:6]]
        positions += [chess.Board("4k3/8/8/8/8/8/4B3/4R1K1 w - - 0 1"), chess.Board()]
        original = candidate._negamax.py_func
        reduced_total = 0
        protected_total = 0
        for source in positions:
            board, state, history, length, keys, moves, data, contexts = scratch(source)
            snapshots: dict[bytes, chess.Move] = {}
            for move in source.legal_moves:
                copy = source.copy(stack=True)
                copy.push(move)
                next_board, next_state = candidate.from_chess(copy)
                snapshots[next_board.tobytes() + next_state.tobytes()] = move
            counts = np.zeros(16, dtype=np.int64)
            visits = 0

            def fake_child(*args: Any, position: chess.Board = source,
                           child_moves: dict[bytes, chess.Move] = snapshots) -> int:
                nonlocal visits, reduced_total, protected_total
                position_key = args[0].tobytes() + args[1].tobytes()
                move = child_moves[position_key]
                protected = (position.is_check() or position.is_capture(move)
                             or bool(move.promotion) or position.gives_check(move) or visits < 3)
                if protected:
                    self.assertEqual(args[2], 3, (position.fen(), move.uci()))
                    protected_total += 1
                elif args[2] == 2:
                    reduced_total += 1
                visits += 1
                return 0

            before = board.copy(), state.copy()
            with patch.object(candidate, "_negamax", side_effect=fake_child):
                original(board, state, 4, 10, 11, 0, time.monotonic() + 2,
                         counts, history, length, keys, moves,
                         np.zeros((2, 64, 64), dtype=np.int64), data, contexts, False, True)
            self.assertEqual(visits, source.legal_moves.count())
            np.testing.assert_array_equal(board, before[0])
            np.testing.assert_array_equal(state, before[1])
        self.assertGreater(protected_total, 10)
        self.assertGreater(reduced_total, 0)

    def test_lmr_timeout_during_verification_unwinds_and_discards_node(self) -> None:
        source = chess.Board()
        board, state, history, length, keys, moves, data, contexts = scratch(source)
        before = board.copy(), state.copy(), history[:length].copy()
        original = candidate._negamax.py_func
        counts = np.zeros(16, dtype=np.int64)
        calls = 0

        def fake_child(*args: Any) -> int:
            nonlocal calls
            calls += 1
            if calls == 4:
                return -12
            if calls == 5:
                args[7][1] = 1
            return 0

        with patch.object(candidate, "_negamax", side_effect=fake_child):
            score = original(board, state, 4, 10, 11, 0, time.monotonic() + 2,
                             counts, history, length, keys, moves,
                             np.zeros((2, 64, 64), dtype=np.int64), data, contexts, True, True)
        self.assertEqual(score, 0)
        self.assertEqual(calls, 5)
        self.assertEqual(counts[1], 1)
        self.assertFalse(np.any(data[:, 2]))
        np.testing.assert_array_equal(board, before[0])
        np.testing.assert_array_equal(state, before[1])
        np.testing.assert_array_equal(history[:length], before[2])

    def test_real_entry_all_configurations_use_warmed_signatures(self) -> None:
        functions = (candidate.compiled_root_search, candidate._negamax, candidate._quiescence)
        signatures = [tuple(function.signatures) for function in functions]
        saved = candidate.USE_SCORE_TT, candidate.USE_LMR
        source = chess.Board()
        for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
            source.push_san(san)
        try:
            for tt, lmr in ((False, False), (True, False), (False, True), (True, True)):
                candidate.set_search_options(tt, lmr)
                candidate._previous_board = None
                started = time.monotonic()
                move = chess.Move.from_uci(candidate.get_move(source.fen(), 1000))
                elapsed = time.monotonic() - started
                self.assertIn(move, source.legal_moves)
                self.assertGreater(candidate.LAST_SEARCH_DEPTH, 0)
                self.assertLess(elapsed, 1.0)
                self.assertEqual([tuple(function.signatures) for function in functions], signatures)
        finally:
            candidate.set_search_options(*saved)
            candidate._previous_board = None

    def test_low_clock_legal_return_and_existing_history_recovery(self) -> None:
        # Keep the inherited sub-20ms fallback policy; it is deliberately not a v8 time change.
        for clock in (1, 5, 50, 500):
            candidate._previous_board = None
            source = chess.Board()
            started = time.monotonic()
            move = chess.Move.from_uci(candidate.get_move(source.fen(), clock))
            elapsed = time.monotonic() - started
            self.assertIn(move, source.legal_moves)
            self.assertLess(elapsed, max(0.05, clock / 1000))
        previous = chess.Board()
        for uci in ("g1f3", "g8f6", "b1c3"):
            previous.push_uci(uci)
        incoming = previous.copy(stack=True)
        incoming.push_uci("b8c6")
        candidate._previous_board = previous.copy(stack=True)
        recovered = candidate._restore_history(incoming.fen())
        self.assertEqual(recovered.move_stack, incoming.move_stack)
        candidate._previous_board = None


if __name__ == "__main__":
    unittest.main()

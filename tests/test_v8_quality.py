"""Small public measurement regressions; no engine import or private online fixtures."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import chess

from tools.online_review import sha256
from tools.v8_quality import configuration_order, labels, quality


class QualityMeasurementTests(unittest.TestCase):
    def test_each_pair_exactly_reverses_for_two_and_four_configurations(self) -> None:
        for choices in (["v7", "both"], ["v7", "tt", "lmr", "both"]):
            for index in range(8):
                first = configuration_order(choices, index, 0)
                second = configuration_order(choices, index, 1)
                self.assertEqual(second, list(reversed(first)))
                self.assertCountEqual(first, choices)
                self.assertCountEqual(second, choices)
                self.assertEqual(len(first), len(set(first)))
        # Rotating by (position + repetition) and then reversing used to cancel.
        self.assertEqual(configuration_order(["v7", "both"], 0, 1), ["both", "v7"])

    def test_teacher_cache_requires_exact_history_even_when_final_fen_matches(self) -> None:
        def position(history: list[str]) -> dict[str, Any]:
            board = chess.Board()
            for move in history:
                board.push_uci(move)
            return {"key": "synthetic", "start_fen": chess.STARTING_FEN, "history": history,
                    "position": {"fen": board.fen()}}

        first = position(["g1f3", "g8f6", "f3g1", "f6g8"])
        different = position(["b1c3", "b8c6", "c3b1", "c6b8"])
        self.assertEqual(first["position"], different["position"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, changed, cache = (
                root / n for n in ("original.jsonl", "other.jsonl", "a.jsonl"))
            original.write_text(json.dumps(first) + "\n")
            changed.write_text(json.dumps(different) + "\n")
            cache.write_text(json.dumps({"key": "synthetic", "root": [], "moves": {}}) + "\n")
            cache.with_suffix(".meta.json").write_text(json.dumps({
                "position_input_sha256": sha256(original), "binary_sha256": "test-teacher",
                "nodes_per_forced_move": 4_000_000,
            }))
            self.assertIn("synthetic", labels([cache], original, [], 4_000_000))
            with self.assertRaises(AssertionError):
                labels([cache], changed, [original], 4_000_000)

    def test_near_equivalent_moves_and_mate_keep_distinct_units(self) -> None:
        root = {"cp": 100, "mate": None, "lowerbound": False, "upperbound": False}
        reference = {"root": [root], "moves": {"e2e4": dict(root, cp=90),
                                               "d2d4": dict(root, cp=None, mate=3)}}
        self.assertEqual(quality(reference, "e2e4")["regret_cp"], 10)
        self.assertIsNone(quality(reference, "d2d4")["regret_cp"])
        self.assertEqual(quality(reference, "d2d4")["mate_transition"], [None, 3])
        self.assertTrue(quality(reference, "g1f3")["missing"])


if __name__ == "__main__":
    unittest.main()

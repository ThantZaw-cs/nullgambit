"""Keep online import honest about starting FEN, duplicates and missing versions."""

import tempfile
import unittest
from pathlib import Path

import chess
import chess.pgn

from tools.online_review import read_games


class OnlineReviewTests(unittest.TestCase):
    def fixture(self, directory: Path) -> chess.pgn.Game:
        # A nonstandard start and a genuine repetition, with no invented opening history.
        board = chess.Board("r3k1nr/ppp2ppp/8/8/8/8/PPP2PPP/R3K1NR b KQkq - 0 20")
        for uci in ("g8f6", "g1f3", "f6g8", "f3g1") * 2:
            board.push_uci(uci)
        game = chess.pgn.Game.from_board(board)
        game.headers.update({"White": "Opponent", "Black": "NullGambit", "Round": "58"})
        game.headers["Result"] = "1/2-1/2"
        (directory / "a.pgn").write_text(str(game) + "\n")
        return game

    def test_real_start_and_repetition_survive_import_without_a_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            game = self.fixture(directory)
            [(record, _)] = read_games(directory)
            self.assertEqual(record["start_fen"], game.board().fen())
            self.assertEqual(record["moves"][0]["history_plies"], 0)
            self.assertEqual(record["moves"][0]["fullmove"], 20)
            self.assertEqual(record["replayed_termination"], "THREEFOLD_REPETITION")
            self.assertEqual(record["version"], "unknown")
            self.assertIsNone(record["log"])

    def test_duplicate_exports_are_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            (directory / "b.pgn").write_bytes((directory / "a.pgn").read_bytes())
            self.assertEqual(len(read_games(directory)), 1)

    def test_long_init_and_later_finish_do_not_identify_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            game = self.fixture(directory)
            (directory / "a.log").write_text(
                "  Round          Rated 58\n  Opponent       Opponent\n"
                f"  Start FEN      {game.board().fen()}\n"
                "  Ready in       21.7 s\n  Finished       2026-09-08 08:45:53 UTC\n"
            )
            [(record, _)] = read_games(directory)
            self.assertEqual(record["version"], "unknown")
            self.assertEqual(record["version_hint"], "unknown")

    def test_conflicting_same_round_export_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            game = self.fixture(directory)
            first = game.variations[0]
            first.variations.clear()
            game.headers["Result"] = "*"
            (directory / "b.pgn").write_text(str(game) + "\n")
            with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
                read_games(directory)


if __name__ == "__main__":
    unittest.main()

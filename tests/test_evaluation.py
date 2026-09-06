"""Independent attack-map checks and positional evaluation properties."""

import random
import unittest

import chess

import agent
from tools.positions import positions


def structure(board: chess.Board) -> int:
    return agent._compiled_structure(
        board.pawns,
        board.knights,
        board.bishops,
        board.rooks,
        board.queens,
        board.kings,
        board.occupied_co[chess.WHITE],
        board.occupied_co[chess.BLACK],
    )


class EvaluationTests(unittest.TestCase):
    def test_attack_maps_match_chess_library(self) -> None:
        rng = random.Random(329)
        board = chess.Board()
        for index in range(250):
            if index % 50 == 0 or board.is_game_over():
                board = chess.Board()
            for square, piece in board.piece_map().items():
                actual = agent._compiled_attacks(
                    piece.piece_type, square, int(piece.color), board.occupied
                )
                self.assertEqual(actual, board.attacks_mask(square), (board.fen(), square))
            self.assertEqual(structure(board), -structure(board.mirror()))
            self.assertLessEqual(abs(agent.evaluate(board) - agent.evaluate(board.mirror())), 1)
            board.push(rng.choice(list(board.legal_moves)))

    def test_intact_pawn_shield_is_preferred(self) -> None:
        board = chess.Board()
        for move in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "O-O", "Bc5"):
            board.push_san(move)
        sheltered = structure(board)
        board.remove_piece_at(chess.F2)
        board.set_piece_at(chess.F4, chess.Piece(chess.PAWN, chess.WHITE))
        board.remove_piece_at(chess.G2)
        board.set_piece_at(chess.G4, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertGreater(sheltered, structure(board))

    def test_passed_pawn_is_preferred(self) -> None:
        board = chess.Board("7k/4p3/4P3/8/8/8/8/K7 w - - 0 1")
        blocked = structure(board)
        board.remove_piece_at(chess.E7)
        board.set_piece_at(chess.A7, chess.Piece(chess.PAWN, chess.BLACK))
        self.assertGreater(structure(board), blocked)

    def test_connected_pawns_beat_isolated_pawns(self) -> None:
        board = chess.Board("7k/8/8/8/3P4/P7/8/K7 w - - 0 1")
        isolated = structure(board)
        board.remove_piece_at(chess.A3)
        board.set_piece_at(chess.E3, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertGreater(structure(board), isolated)

    def test_doubled_pawns_are_penalized(self) -> None:
        board = chess.Board("7k/8/8/8/3P4/3P4/8/K7 w - - 0 1")
        doubled = structure(board)
        board.remove_piece_at(chess.D3)
        board.set_piece_at(chess.C3, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertGreater(structure(board), doubled)

    def test_rook_prefers_open_file(self) -> None:
        board = chess.Board("r2q2k1/7p/8/8/8/8/P7/R2Q2K1 w - - 0 1")
        closed = structure(board)
        board.remove_piece_at(chess.A1)
        board.set_piece_at(chess.B1, chess.Piece(chess.ROOK, chess.WHITE))
        self.assertGreater(structure(board), closed)

    def test_king_shelter_does_not_penalize_endgame_activity(self) -> None:
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1")
        sheltered = structure(board)
        board.remove_piece_at(chess.G1)
        board.set_piece_at(chess.D4, chess.Piece(chess.KING, chess.WHITE))
        self.assertEqual(structure(board), sheltered)

    def test_all_promotion_rank_and_corner_cases(self) -> None:
        for white_king, black_king in ((chess.A1, chess.H8), (chess.H1, chess.A8)):
            for pawn_square in (chess.A2, chess.H2, chess.A7, chess.H7):
                board = chess.Board(None)
                board.set_piece_at(white_king, chess.Piece(chess.KING, chess.WHITE))
                board.set_piece_at(black_king, chess.Piece(chess.KING, chess.BLACK))
                board.set_piece_at(pawn_square, chess.Piece(chess.PAWN, chess.WHITE))
                self.assertEqual(structure(board), -structure(board.mirror()))

    def test_holdout_positions_are_valid_and_distinct(self) -> None:
        development = {fen for _, fen in positions()}
        holdout = positions("holdout") + positions("confirmation")
        self.assertEqual(len({fen for _, fen in holdout}), len(holdout))
        for name, fen in holdout:
            self.assertTrue(chess.Board(fen).is_valid(), name)
            self.assertNotIn(fen, development)


if __name__ == "__main__":
    unittest.main()

"""An original classical engine with a bounded, iterative alpha-beta search."""

import time
from collections.abc import Callable
from typing import NamedTuple, cast

import chess
import numpy as np
from numba import njit

MATE = 100_000
INFINITY = MATE + 1_000
MAX_PLY = 64
QUIESCENCE_DEPTH = 8
PIECE_VALUES = (0, 100, 320, 335, 500, 900, 0)
PHASE_WEIGHTS = (0, 0, 1, 1, 2, 4, 0)
FULL_PHASE = 24
TABLE_LIMIT = 20_000
EXACT, LOWER, UPPER = 0, 1, 2
type PositionKey = tuple[int, ...]
type Repetitions = dict[PositionKey, int]
type ScoreKey = tuple[PositionKey, int, frozenset[tuple[PositionKey, int]]]


def _piece_square(piece: int, square: int, endgame: bool) -> int:
    """Build our tables from simple geometry, with squares viewed by White."""
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    # Twice the distance from the nearest central file/rank: 0, 2, 4, 6.
    file_distance = abs(2 * file - 7) - 1
    rank_distance = abs(2 * rank - 7) - 1
    centrality = 12 - file_distance - rank_distance
    if piece == chess.PAWN:
        advance = max(0, rank - 1)
        if endgame:
            return advance * advance * 5 + (6 - file_distance) * 2
        return advance * 7 + (6 - file_distance) * min(rank, 4) * 2
    if piece == chess.KNIGHT:
        return centrality * 6 - (12 if rank == 0 else 0)
    if piece == chess.BISHOP:
        return centrality * 3 + min(rank, 3) * 4
    if piece == chess.ROOK:
        return (20 if rank == 6 else 0) + (6 - file_distance) * 2
    if piece == chess.QUEEN:
        return centrality * (3 if endgame else 1)
    if piece == chess.KING:
        if endgame:
            return centrality * 6
        # Prefer a king tucked away on its home rank before the endgame.
        shelter = 25 if rank == 0 and file in (1, 2, 6) else 0
        return shelter - rank * 15 - (6 - file_distance) * 5
    return 0


MIDDLEGAME_TABLE = tuple(
    tuple(PIECE_VALUES[piece] + _piece_square(piece, square, False) for square in chess.SQUARES)
    for piece in range(7)
)
ENDGAME_TABLE = tuple(
    tuple(PIECE_VALUES[piece] + _piece_square(piece, square, True) for square in chess.SQUARES)
    for piece in range(7)
)


_MG = np.asarray(MIDDLEGAME_TABLE, dtype=np.int64)
_EG = np.asarray(ENDGAME_TABLE, dtype=np.int64)


def _evaluate_numeric(
    pawns: int,
    knights: int,
    bishops: int,
    rooks: int,
    queens: int,
    kings: int,
    white: int,
    black: int,
) -> int:
    """Evaluate eight bitboards directly, without allocating a board encoding."""
    middlegame = endgame = phase = 0
    white_bishops = black_bishops = 0
    masks = (pawns, knights, bishops, rooks, queens, kings)
    for square in range(64):
        bit = np.uint64(1) << np.uint64(square)
        if not (white | black) & bit:
            continue
        is_white = bool(white & bit)
        sign = 1 if is_white else -1
        oriented = square if is_white else square ^ 56
        for index in range(6):
            if masks[index] & bit:
                piece = index + 1
                phase += PHASE_WEIGHTS[piece]
                middlegame += sign * _MG[piece, oriented]
                endgame += sign * _EG[piece, oriented]
                if piece == 3:
                    white_bishops += int(is_white)
                    black_bishops += int(not is_white)
                break
    bishop_pair = int(white_bishops >= 2) - int(black_bishops >= 2)
    middlegame += bishop_pair * 25
    endgame += bishop_pair * 40
    phase = min(phase, FULL_PHASE)
    return int((middlegame * phase + endgame * (FULL_PHASE - phase)) // FULL_PHASE)


# An explicit unsigned signature compiles at import and accepts the high bit of h8.
# No disk cache, extra threads, or first-move compilation is needed.
_compiled_evaluate = cast(
    Callable[[int, int, int, int, int, int, int, int], int],
    njit("int64(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", cache=False)(
        _evaluate_numeric
    ),
)


def evaluate(board: chess.Board) -> int:
    """Material and piece placement, smoothly switching to an endgame king."""
    score = _compiled_evaluate(
        board.pawns,
        board.knights,
        board.bishops,
        board.rooks,
        board.queens,
        board.kings,
        board.occupied_co[chess.WHITE],
        board.occupied_co[chess.BLACK],
    )
    return score if board.turn == chess.WHITE else -score


def _position_key(board: chess.Board) -> PositionKey:
    """Board identity; score caching additionally includes clock and history."""
    return (
        board.pawns,
        board.knights,
        board.bishops,
        board.rooks,
        board.queens,
        board.kings,
        board.occupied_co[chess.WHITE],
        board.occupied_co[chess.BLACK],
        int(board.turn),
        board.castling_rights,
        board.ep_square if board.ep_square is not None and board.has_legal_en_passant() else -1,
    )


class SearchTimeout(Exception):
    """Unwind the current iteration without losing the last completed result."""


class Entry(NamedTuple):
    depth: int
    score: int
    bound: int
    move: chess.Move


def _store_mate(score: int, ply: int) -> int:
    if score >= MATE - MAX_PLY:
        return score + ply
    if score <= -MATE + MAX_PLY:
        return score - ply
    return score


def _load_mate(score: int, ply: int) -> int:
    return _store_mate(score, -ply)


class Search:
    def __init__(self, deadline: float, table: dict[ScoreKey, Entry] | None = None) -> None:
        self.deadline = deadline
        self.nodes = 0
        self.completed_depth = 0
        self.best_moves: dict[tuple[int, ...], chess.Move] = {}
        self.killers: list[list[chess.Move]] = [[] for _ in range(MAX_PLY)]
        self.history: dict[tuple[chess.Color, int, int], int] = {}
        self.table: dict[ScoreKey, Entry] = {} if table is None else table
        self.table_hits = 0
        self.repetitions: Repetitions = {}
        self.undo_history: list[tuple[PositionKey, Repetitions | None]] = []

    def prepare_history(self, board: chess.Board) -> None:
        previous = board.copy()
        self.repetitions = {}
        while True:
            key = _position_key(previous)
            self.repetitions[key] = self.repetitions.get(key, 0) + 1
            if not previous.move_stack or previous.halfmove_clock == 0:
                break
            previous.pop()

    def push(self, board: chess.Board, move: chess.Move) -> None:
        board.push(move)
        saved = None
        if board.halfmove_clock == 0:
            saved = self.repetitions
            self.repetitions = {}
        key = _position_key(board)
        self.repetitions[key] = self.repetitions.get(key, 0) + 1
        self.undo_history.append((key, saved))

    def pop(self, board: chess.Board) -> None:
        key, saved = self.undo_history.pop()
        if saved is not None:
            self.repetitions = saved
        elif self.repetitions[key] == 1:
            del self.repetitions[key]
        else:
            self.repetitions[key] -= 1
        board.pop()

    def score_key(self, board: chess.Board) -> ScoreKey:
        # Exact counts prevent a cached score from overlooking a claimable draw
        # reached through another path. Pawn moves and captures reset the context.
        return _position_key(board), board.halfmove_clock, frozenset(self.repetitions.items())

    def check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            raise SearchTimeout

    def visit(self) -> None:
        self.nodes += 1
        self.check_time()

    def ordered_moves(
        self, board: chess.Board, moves: list[chess.Move], ply: int
    ) -> list[chess.Move]:
        preferred = self.best_moves.get(_position_key(board))

        def priority(move: chess.Move) -> int:
            if move == preferred:
                return 1_000_000
            score = 0
            if board.is_capture(move):
                victim = board.piece_type_at(move.to_square) or chess.PAWN
                attacker = board.piece_type_at(move.from_square) or chess.PAWN
                score += 100_000 + 16 * PIECE_VALUES[victim] - PIECE_VALUES[attacker]
            if move.promotion:
                score += 80_000 + PIECE_VALUES[move.promotion]
            if score:
                return score
            if move in self.killers[ply]:
                return 50_000 - self.killers[ply].index(move)
            return min(40_000, self.history.get((board.turn, move.from_square, move.to_square), 0))

        return sorted(moves, key=priority, reverse=True)

    def terminal(self, board: chess.Board, moves: list[chess.Move], ply: int) -> int | None:
        # Checkmate takes precedence over the fifty-move rule.
        if not moves:
            return -MATE + ply if board.is_check() else 0
        if (
            board.halfmove_clock >= 100
            or board.is_insufficient_material()
            or self.repetitions.get(_position_key(board), 0) >= 3
        ):
            return 0
        return None

    def quiescence(self, board: chess.Board, alpha: int, beta: int, ply: int, depth: int) -> int:
        if ply == 0:
            self.prepare_history(board)
        self.visit()
        in_check = board.is_check()
        # Stalemate must be checked even on a stand-pat cutoff, but only one
        # legal move is needed to rule it out. Avoid generating every quiet move.
        if in_check:
            moves = list(board.legal_moves)
        else:
            first = next(board.generate_legal_moves(), None)
            moves = [] if first is None else [first]
        terminal = self.terminal(board, moves, ply)
        if terminal is not None:
            return terminal
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        if not in_check:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            alpha = max(alpha, stand_pat)
            if depth <= 0:
                return alpha
            moves = list(board.generate_legal_captures())
            promotion_rank = chess.BB_RANK_7 if board.turn else chess.BB_RANK_2
            promotion_pawns = board.pawns & board.occupied_co[board.turn] & promotion_rank
            if promotion_pawns:
                moves.extend(
                    board.generate_legal_moves(
                        from_mask=promotion_pawns, to_mask=chess.BB_ALL ^ board.occupied
                    )
                )
        # In check, standing pat is illegal: search every evasion, including quiet ones.
        for move in self.ordered_moves(board, moves, ply):
            self.check_time()
            self.push(board, move)
            try:
                score = -self.quiescence(board, -beta, -alpha, ply + 1, depth - 1)
            finally:
                self.pop(board)
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        if depth <= 0:
            return self.quiescence(board, alpha, beta, ply, QUIESCENCE_DEPTH)
        if ply == 0:
            self.prepare_history(board)
        self.visit()
        moves = list(board.legal_moves)
        terminal = self.terminal(board, moves, ply)
        if terminal is not None:
            return terminal
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        in_check = board.is_check()
        if in_check:
            # A forced evasion should not consume the whole remaining horizon.
            depth += 1
        key = _position_key(board)
        score_key = self.score_key(board)
        entry = self.table.get(score_key)
        if entry is not None:
            self.best_moves[key] = entry.move
            if entry.depth >= depth:
                score = _load_mate(entry.score, ply)
                if (
                    entry.bound == EXACT
                    or (entry.bound == LOWER and score >= beta)
                    or (entry.bound == UPPER and score <= alpha)
                ):
                    self.table_hits += 1
                    return score
        original_alpha = alpha
        best_score = -INFINITY
        best_move = moves[0]
        for index, move in enumerate(self.ordered_moves(board, moves, ply)):
            self.check_time()
            quiet = not board.is_capture(move) and move.promotion is None
            self.push(board, move)
            try:
                if index == 0:
                    score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
                else:
                    child_depth = depth - 1
                    reduced = (
                        depth >= 3
                        and index >= 4
                        and quiet
                        and not in_check
                        and not board.is_check()
                        and beta == alpha + 1
                    )
                    if reduced:
                        # Try late quiet moves one ply shallower at non-PV nodes.
                        # A move that improves alpha must pass a full-depth search.
                        child_depth -= 1
                    # First ask whether this move beats the incumbent. Only a
                    # promising result needs another search with the full window.
                    score = -self.negamax(board, child_depth, -alpha - 1, -alpha, ply + 1)
                    if reduced and score > alpha:
                        score = -self.negamax(board, depth - 1, -alpha - 1, -alpha, ply + 1)
                    if alpha < score < beta:
                        score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
            finally:
                self.pop(board)
            if score > best_score:
                best_score, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                if quiet:
                    killers = self.killers[ply]
                    if move not in killers:
                        killers.insert(0, move)
                        del killers[2:]
                    history_key = (board.turn, move.from_square, move.to_square)
                    self.history[history_key] = self.history.get(history_key, 0) + depth * depth
                break
        self.best_moves[key] = best_move
        if len(self.table) < TABLE_LIMIT or score_key in self.table:
            bound = (
                UPPER if best_score <= original_alpha else LOWER if best_score >= beta else EXACT
            )
            if entry is None or entry.depth <= depth:
                self.table[score_key] = Entry(depth, _store_mate(best_score, ply), bound, best_move)
        return best_score

    def choose(self, board: chess.Board, fallback: chess.Move) -> chess.Move:
        best = fallback
        key = _position_key(board)
        for depth in range(1, MAX_PLY):
            try:
                score = self.negamax(board, depth, -INFINITY, INFINITY, 0)
            except SearchTimeout:
                break
            best = self.best_moves.get(key, best)
            self.completed_depth = depth
            if abs(score) >= MATE - MAX_PLY or key not in self.best_moves:
                break
        return best


_previous_board: chess.Board | None = None
_transpositions: dict[ScoreKey, Entry] = {}


def _restore_history(fen: str) -> chess.Board:
    """Recover the opponent's last move so repetition history survives FEN input."""
    incoming = chess.Board(fen)
    if _previous_board is None:
        return incoming
    previous = _previous_board
    # A normal next request is exactly one opponent move after our saved board.
    if previous.turn == incoming.turn or incoming.ply() != previous.ply() + 1:
        return incoming
    target = incoming.fen()
    for move in list(previous.legal_moves):
        previous.push(move)
        if previous.fen() == target:
            return previous
        previous.pop()
    return incoming


def get_move(fen: str, time_left_ms: int) -> str:
    """Return a legal UCI move, budgeting from the supplied remaining wall clock."""
    global _previous_board

    started = time.monotonic()
    # Reserve time for FEN handling, unwinding, and the runner's response overhead.
    remaining = max(0, time_left_ms) / 1000.0
    reserve = max(0.01, min(0.25, remaining * 0.1))
    budget = min(2.5, remaining / 35.0, max(0.0, remaining - reserve))
    if len(_transpositions) >= TABLE_LIMIT and remaining > 1.0:
        _transpositions.clear()
    board = chess.Board(fen) if budget < 0.01 else _restore_history(fen)
    moves = list(board.legal_moves)
    if not moves:
        # The referee never requests a move from a finished position.
        return "0000"
    best = moves[0]
    if len(moves) > 1 and budget > 0:
        best = Search(started + budget, _transpositions).choose(board, best)
    board.push(best)
    _previous_board = board
    return best.uci()


# Exercise the actual call path at import, including the high bits of Black's pieces.
evaluate(chess.Board())

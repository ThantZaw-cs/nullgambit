"""An original classical engine with a bounded, iterative alpha-beta search."""

import time

import chess

MATE = 100_000
INFINITY = MATE + 1_000
MAX_PLY = 64
QUIESCENCE_DEPTH = 8
PIECE_VALUES = (0, 100, 320, 335, 500, 900, 0)
PHASE_WEIGHTS = (0, 0, 1, 1, 2, 4, 0)
FULL_PHASE = 24


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


def evaluate(board: chess.Board) -> int:
    """Material and piece placement, smoothly switching to an endgame king."""
    middlegame = endgame = phase = 0
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        mirror = 0 if color == chess.WHITE else 56
        for piece in chess.PIECE_TYPES:
            squares = board.pieces_mask(piece, color)
            count = squares.bit_count()
            phase += PHASE_WEIGHTS[piece] * count
            for square in chess.scan_forward(squares):
                oriented = square ^ mirror
                middlegame += sign * MIDDLEGAME_TABLE[piece][oriented]
                endgame += sign * ENDGAME_TABLE[piece][oriented]
            if piece == chess.BISHOP and count >= 2:
                middlegame += sign * 25
                endgame += sign * 40
    phase = min(phase, FULL_PHASE)
    score = (middlegame * phase + endgame * (FULL_PHASE - phase)) // FULL_PHASE
    return score if board.turn == chess.WHITE else -score


def _position_key(board: chess.Board) -> tuple[int, ...]:
    """Keys are used only for move ordering, never to reuse a draw-sensitive score."""
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
        board.ep_square if board.ep_square is not None else -1,
    )


class SearchTimeout(Exception):
    """Unwind the current iteration without losing the last completed result."""


class Search:
    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.nodes = 0
        self.completed_depth = 0
        self.best_moves: dict[tuple[int, ...], chess.Move] = {}
        self.killers: list[list[chess.Move]] = [[] for _ in range(MAX_PLY)]
        self.history: dict[tuple[chess.Color, int, int], int] = {}

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
            or board.is_repetition(3)
        ):
            return 0
        return None

    def quiescence(self, board: chess.Board, alpha: int, beta: int, ply: int, depth: int) -> int:
        self.visit()
        moves = list(board.legal_moves)
        terminal = self.terminal(board, moves, ply)
        if terminal is not None:
            return terminal
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        in_check = board.is_check()
        if not in_check:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            alpha = max(alpha, stand_pat)
            if depth <= 0:
                return alpha
            moves = [move for move in moves if board.is_capture(move) or move.promotion]
        # In check, standing pat is illegal: search every evasion, including quiet ones.
        for move in self.ordered_moves(board, moves, ply):
            self.check_time()
            board.push(move)
            try:
                score = -self.quiescence(board, -beta, -alpha, ply + 1, depth - 1)
            finally:
                board.pop()
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        if depth <= 0:
            return self.quiescence(board, alpha, beta, ply, QUIESCENCE_DEPTH)
        self.visit()
        moves = list(board.legal_moves)
        terminal = self.terminal(board, moves, ply)
        if terminal is not None:
            return terminal
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        key = _position_key(board)
        best_score = -INFINITY
        best_move = moves[0]
        for move in self.ordered_moves(board, moves, ply):
            self.check_time()
            quiet = not board.is_capture(move) and move.promotion is None
            board.push(move)
            try:
                score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
            finally:
                board.pop()
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
    board = chess.Board(fen) if budget < 0.01 else _restore_history(fen)
    moves = list(board.legal_moves)
    if not moves:
        # The referee never requests a move from a finished position.
        return "0000"
    best = moves[0]
    if len(moves) > 1 and budget > 0:
        best = Search(started + budget).choose(board, best)
    board.push(best)
    _previous_board = board
    return best.uci()

"""Original compiled move-generation prototype, isolated from the stable agent."""

import hashlib
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import chess
import numpy as np
from numba import njit, objmode

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6
WHITE, BLACK = 1, -1
WK, WQ, BK, BQ = 1, 2, 4, 8
EP_FLAG, CASTLE_FLAG = 1 << 15, 1 << 16
MAX_PLY = 64
TT_LIMIT = 65_536
PROMOTIONS = (KNIGHT, BISHOP, ROOK, QUEEN)
KNIGHT_STEPS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_STEPS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


@njit(cache=False)
def encode_move(source: int, target: int, promotion: int = 0, flags: int = 0) -> int:
    return source | (target << 6) | (promotion << 12) | flags


@njit(cache=False)
def _attacked(board: np.ndarray, square: int, attacker: int) -> bool:
    file, rank = square & 7, square >> 3
    pawn_rank = rank - attacker
    if 0 <= pawn_rank < 8:
        for pawn_file in (file - 1, file + 1):
            if 0 <= pawn_file < 8 and board[pawn_rank * 8 + pawn_file] == attacker * PAWN:
                return True
    for df, dr in KNIGHT_STEPS:
        f, r = file + df, rank + dr
        if 0 <= f < 8 and 0 <= r < 8 and board[r * 8 + f] == attacker * KNIGHT:
            return True
    for df, dr in KING_STEPS:
        f, r = file + df, rank + dr
        if 0 <= f < 8 and 0 <= r < 8 and board[r * 8 + f] == attacker * KING:
            return True
    for index, (df, dr) in enumerate(DIRECTIONS):
        f, r = file + df, rank + dr
        while 0 <= f < 8 and 0 <= r < 8:
            piece = board[r * 8 + f]
            if piece:
                kind = abs(piece)
                if piece * attacker > 0 and (
                    kind == QUEEN or kind == (ROOK if index < 4 else BISHOP)
                ):
                    return True
                break
            f += df
            r += dr
    return False


@njit(cache=False)
def _append(
    moves: np.ndarray, count: int, source: int, target: int, promotion: int = 0, flags: int = 0
) -> int:
    moves[count] = encode_move(source, target, promotion, flags)
    return count + 1


@njit(cache=False)
def _pseudo_moves(board: np.ndarray, state: np.ndarray, moves: np.ndarray) -> int:
    side, count = int(state[0]), 0
    for source in range(64):
        piece = int(board[source])
        if piece * side <= 0:
            continue
        kind, file, rank = abs(piece), source & 7, source >> 3
        if kind == PAWN:
            target = source + side * 8
            promotion_rank = 7 if side == WHITE else 0
            if 0 <= target < 64 and board[target] == 0:
                if target >> 3 == promotion_rank:
                    for promotion in PROMOTIONS:
                        count = _append(moves, count, source, target, promotion)
                else:
                    count = _append(moves, count, source, target)
                    start_rank = 1 if side == WHITE else 6
                    target2 = source + side * 16
                    if rank == start_rank and board[target2] == 0:
                        count = _append(moves, count, source, target2)
            for df in (-1, 1):
                f, target = file + df, source + side * 8 + df
                if not 0 <= f < 8 or not 0 <= target < 64:
                    continue
                if board[target] * side < 0 or target == state[2]:
                    flag = EP_FLAG if target == state[2] else 0
                    if target >> 3 == promotion_rank:
                        for promotion in PROMOTIONS:
                            count = _append(moves, count, source, target, promotion, flag)
                    else:
                        count = _append(moves, count, source, target, 0, flag)
        elif kind == KNIGHT:
            for df, dr in KNIGHT_STEPS:
                f, r = file + df, rank + dr
                if 0 <= f < 8 and 0 <= r < 8 and board[r * 8 + f] * side <= 0:
                    count = _append(moves, count, source, r * 8 + f)
        elif kind in (BISHOP, ROOK, QUEEN):
            for index, (df, dr) in enumerate(DIRECTIONS):
                if (kind == BISHOP and index < 4) or (kind == ROOK and index >= 4):
                    continue
                f, r = file + df, rank + dr
                while 0 <= f < 8 and 0 <= r < 8:
                    target = r * 8 + f
                    if board[target] * side > 0:
                        break
                    count = _append(moves, count, source, target)
                    if board[target]:
                        break
                    f += df
                    r += dr
        else:
            for df, dr in KING_STEPS:
                f, r = file + df, rank + dr
                if 0 <= f < 8 and 0 <= r < 8 and board[r * 8 + f] * side <= 0:
                    count = _append(moves, count, source, r * 8 + f)
            rights = int(state[1])
            if side == WHITE and source == 4:
                if rights & WK and board[5] == board[6] == 0 and board[7] == ROOK:
                    count = _append(moves, count, 4, 6, 0, CASTLE_FLAG)
                if rights & WQ and board[1] == board[2] == board[3] == 0 and board[0] == ROOK:
                    count = _append(moves, count, 4, 2, 0, CASTLE_FLAG)
            elif side == BLACK and source == 60:
                if rights & BK and board[61] == board[62] == 0 and board[63] == -ROOK:
                    count = _append(moves, count, 60, 62, 0, CASTLE_FLAG)
                if rights & BQ and board[57] == board[58] == board[59] == 0 and board[56] == -ROOK:
                    count = _append(moves, count, 60, 58, 0, CASTLE_FLAG)
    return count


@njit(cache=False)
def _make(board: np.ndarray, state: np.ndarray, move: int, undo: np.ndarray) -> None:
    source, target = move & 63, (move >> 6) & 63
    piece, captured = int(board[source]), int(board[target])
    for index in range(5):
        undo[index] = state[index]
    undo[5] = source
    undo[6] = target
    undo[7] = piece
    undo[8] = captured
    undo[9] = -1
    if move & EP_FLAG:
        capture_square = target - (8 if piece > 0 else -8)
        undo[9] = capture_square
        captured = int(board[capture_square])
        undo[8] = captured
        board[capture_square] = 0
    board[source] = 0
    promotion = (move >> 12) & 7
    board[target] = (1 if piece > 0 else -1) * promotion if promotion else piece
    if move & CASTLE_FLAG:
        rook_source = 7 if target == 6 else 0 if target == 2 else 63 if target == 62 else 56
        rook_target = 5 if target == 6 else 3 if target == 2 else 61 if target == 62 else 59
        undo[9] = rook_source
        undo[8] = rook_target
        board[rook_target], board[rook_source] = board[rook_source], 0
    rights = int(state[1])
    if source == 4 or target == 4:
        rights &= ~(WK | WQ)
    if source == 60 or target == 60:
        rights &= ~(BK | BQ)
    for square, mask in ((0, WQ), (7, WK), (56, BQ), (63, BK)):
        if source == square or target == square:
            rights &= ~mask
    state[1], state[2] = rights, -1
    if abs(piece) == PAWN and abs(target - source) == 16:
        state[2] = (source + target) // 2
    state[3] = 0 if abs(piece) == PAWN or captured else state[3] + 1
    if piece < 0:
        state[4] += 1
    state[0] = -state[0]


@njit(cache=False)
def _unmake(board: np.ndarray, state: np.ndarray, undo: np.ndarray) -> None:
    source = int(undo[5])
    target = int(undo[6])
    piece = int(undo[7])
    captured = int(undo[8])
    auxiliary = int(undo[9])
    state[:5] = undo[:5]
    board[source], board[target] = piece, captured if auxiliary < 0 else 0
    if auxiliary >= 0:
        if abs(piece) == KING:
            board[auxiliary], board[captured] = board[captured], 0
        else:
            board[auxiliary] = captured


@njit(cache=False)
def _legal_moves(board: np.ndarray, state: np.ndarray, output: np.ndarray) -> int:
    pseudo = np.empty(256, dtype=np.int64)
    count, legal = _pseudo_moves(board, state, pseudo), 0
    mover = int(state[0])
    for index in range(count):
        move = int(pseudo[index])
        source, target = move & 63, (move >> 6) & 63
        if move & CASTLE_FLAG:
            transit = source + (1 if target > source else -1)
            if _attacked(board, source, -mover) or _attacked(board, transit, -mover):
                continue
        undo = np.empty(10, dtype=np.int64)
        _make(board, state, move, undo)
        king = -1
        for square in range(64):
            if board[square] == mover * KING:
                king = square
                break
        valid = king >= 0 and not _attacked(board, king, -mover)
        _unmake(board, state, undo)
        if valid:
            output[legal], legal = move, legal + 1
    return legal


compiled_legal_moves = _legal_moves
compiled_make = _make
compiled_unmake = _unmake


@njit(cache=False)
def _perft(board: np.ndarray, state: np.ndarray, depth: int) -> int:
    if depth == 0:
        return 1
    moves = np.empty(256, dtype=np.int64)
    count = _legal_moves(board, state, moves)
    if depth == 1:
        return count
    nodes = 0
    for index in range(count):
        undo = np.empty(10, dtype=np.int64)
        _make(board, state, int(moves[index]), undo)
        nodes += _perft(board, state, depth - 1)
        _unmake(board, state, undo)
    return nodes


compiled_perft = _perft


def from_chess(source: chess.Board) -> tuple[np.ndarray, np.ndarray]:
    board = np.zeros(64, dtype=np.int8)
    for square, piece in source.piece_map().items():
        board[square] = piece.piece_type if piece.color else -piece.piece_type
    rights = 0
    for color, kingside, mask in (
        (chess.WHITE, True, WK),
        (chess.WHITE, False, WQ),
        (chess.BLACK, True, BK),
        (chess.BLACK, False, BQ),
    ):
        if (
            source.has_kingside_castling_rights(color)
            if kingside
            else source.has_queenside_castling_rights(color)
        ):
            rights |= mask
    state = np.asarray(
        (
            WHITE if source.turn else BLACK,
            rights,
            source.ep_square if source.ep_square is not None else -1,
            source.halfmove_clock,
            source.fullmove_number,
        ),
        dtype=np.int64,
    )
    return board, state


def move_to_uci(move: int) -> str:
    promotion = (move >> 12) & 7
    suffix = "" if not promotion else chess.piece_symbol(promotion)
    return chess.square_name(move & 63) + chess.square_name((move >> 6) & 63) + suffix


def legal_uci(source: chess.Board) -> set[str]:
    board, state = from_chess(source)
    moves = np.empty(256, dtype=np.int64)
    count = compiled_legal_moves(board, state, moves)
    return {move_to_uci(int(move)) for move in moves[:count]}


def perft(source: chess.Board, depth: int) -> int:
    board, state = from_chess(source)
    return int(compiled_perft(board, state, depth))


_warm_board, _warm_state = from_chess(chess.Board())
_warm_moves = np.empty(256, dtype=np.int64)
_started = time.monotonic()
compiled_legal_moves(_warm_board, _warm_state, _warm_moves)
WARMUP_SECONDS = time.monotonic() - _started


STATIC_VALUES = (0, 100, 320, 335, 500, 900, 0)
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
    tuple(STATIC_VALUES[piece] + _piece_square(piece, square, False) for square in chess.SQUARES)
    for piece in range(7)
)
ENDGAME_TABLE = tuple(
    tuple(STATIC_VALUES[piece] + _piece_square(piece, square, True) for square in chess.SQUARES)
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


_PAWN_ATTACKS = np.asarray(chess.BB_PAWN_ATTACKS, dtype=np.uint64)
_KNIGHT_ATTACKS = np.asarray(chess.BB_KNIGHT_ATTACKS, dtype=np.uint64)
_KING_ATTACKS = np.asarray(chess.BB_KING_ATTACKS, dtype=np.uint64)
_PASSED_MASKS = np.asarray(
    [
        [
            sum(
                chess.BB_SQUARES[target]
                for target in chess.SQUARES
                if abs(chess.square_file(target) - chess.square_file(square)) <= 1
                and (
                    chess.square_rank(target) > chess.square_rank(square)
                    if color
                    else chess.square_rank(target) < chess.square_rank(square)
                )
            )
            for square in chess.SQUARES
        ]
        for color in range(2)
    ],
    dtype=np.uint64,
)


def _attacks_numeric(piece: int, square: int, side: int, occupied: int) -> int:
    """Pseudo-attacks for evaluation, including the first blocker on each ray."""
    if piece == 1:
        return int(_PAWN_ATTACKS[side, square])
    if piece == 2:
        return int(_KNIGHT_ATTACKS[square])
    if piece == 6:
        return int(_KING_ATTACKS[square])
    result = np.uint64(0)
    file, rank = square % 8, square // 8
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    for index in range(8):
        if (piece == 3 and index < 4) or (piece == 4 and index >= 4):
            continue
        df, dr = directions[index]
        f, r = file + df, rank + dr
        while 0 <= f < 8 and 0 <= r < 8:
            bit = np.uint64(1) << np.uint64(r * 8 + f)
            result |= bit
            if occupied & bit:
                break
            f += df
            r += dr
    return int(result)


_compiled_attacks = cast(
    Callable[[int, int, int, int], int],
    njit("uint64(int64,int64,int64,uint64)", cache=False)(_attacks_numeric),
)


def _structure_numeric(
    pawns: int,
    knights: int,
    bishops: int,
    rooks: int,
    queens: int,
    kings: int,
    white: int,
    black: int,
) -> int:
    """Pawn structure, rook files, and phase-scaled shelter and king pressure."""
    files = np.zeros((2, 8), dtype=np.int64)
    king_squares = np.full(2, -1, dtype=np.int64)
    masks = (pawns, knights, bishops, rooks, queens, kings)
    phase = 0
    for square in range(64):
        bit = np.uint64(1) << np.uint64(square)
        if not (white | black) & bit:
            continue
        side = int(bool(white & bit))
        if pawns & bit:
            files[side, square % 8] += 1
        if kings & bit:
            king_squares[side] = square
        for index in range(6):
            if masks[index] & bit:
                phase += PHASE_WEIGHTS[index + 1]
                break

    middlegame = endgame = 0
    for side in range(2):
        own = white if side else black
        enemy = black if side else white
        sign = 1 if side else -1
        own_pawns, enemy_pawns = pawns & own, pawns & enemy
        mg = eg = pressure = 0
        enemy_king = king_squares[1 - side]
        zone = _KING_ATTACKS[enemy_king] if enemy_king >= 0 else np.uint64(0)
        for file in range(8):
            extra = max(0, files[side, file] - 1)
            mg -= 12 * extra
            eg -= 18 * extra
        for square in range(64):
            bit = np.uint64(1) << np.uint64(square)
            if not own & bit:
                continue
            file, rank = square % 8, square // 8
            piece = 0
            for index in range(6):
                if masks[index] & bit:
                    piece = index + 1
                    break
            if piece == 1:
                neighbours = 0
                if file > 0:
                    neighbours += files[side, file - 1]
                if file < 7:
                    neighbours += files[side, file + 1]
                if neighbours == 0:
                    mg -= 10
                    eg -= 12
                if not _PASSED_MASKS[side, square] & enemy_pawns:
                    advance = rank if side else 7 - rank
                    bonus = (0, 0, 4, 10, 22, 45, 80, 0)[advance]
                    mg += bonus // 3
                    eg += bonus
                if _PAWN_ATTACKS[1 - side, square] & own_pawns:
                    mg += 6
                    eg += 8
            elif piece == 4 and files[side, file] == 0:
                mg += 20 if files[1 - side, file] == 0 else 10
                eg += 10 if files[1 - side, file] == 0 else 5
            if piece != 6 and zone:
                hits = np.uint64(_compiled_attacks(piece, square, side, white | black)) & zone
                count = 0
                while hits:
                    count += 1
                    hits &= hits - np.uint64(1)
                pressure += count * (0, 1, 2, 2, 3, 5, 0)[piece]
        # Multiple pieces attacking the king zone matter more than one lone attacker.
        danger = min(240, pressure * pressure * 2)
        if not queens & own:
            danger //= 4
        mg += danger

        king = king_squares[side]
        if king >= 0:
            file, rank = king % 8, king // 8
            advance = rank if side else 7 - rank
            direction = 1 if side else -1
            if advance <= 2:
                for f in range(max(0, file - 1), min(8, file + 2)):
                    near = np.uint64(1) << np.uint64((rank + direction) * 8 + f)
                    far = np.uint64(1) << np.uint64((rank + 2 * direction) * 8 + f)
                    mg += 12 if near & own_pawns else 6 if far & own_pawns else -15
                    if files[side, f] == 0 and (rooks | queens) & enemy:
                        mg -= 8
        middlegame += sign * mg
        endgame += sign * eg
    phase = min(phase, FULL_PHASE)
    numerator = int(middlegame * phase + endgame * (FULL_PHASE - phase))
    return numerator // FULL_PHASE if numerator >= 0 else -((-numerator) // FULL_PHASE)


_compiled_structure = cast(
    Callable[[int, int, int, int, int, int, int, int], int],
    njit("int64(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", cache=False)(
        _structure_numeric
    ),
)


@njit(cache=False)
def _evaluate(board: np.ndarray, side: int) -> int:
    masks = np.zeros(6, dtype=np.uint64)
    white = np.uint64(0)
    black = np.uint64(0)
    for square in range(64):
        piece = int(board[square])
        if piece == 0:
            continue
        bit = np.uint64(1) << np.uint64(square)
        masks[abs(piece) - 1] |= bit
        if piece > 0:
            white |= bit
        else:
            black |= bit
    score = _compiled_evaluate(
        masks[0], masks[1], masks[2], masks[3], masks[4], masks[5], int(white), int(black)
    ) + _compiled_structure(
        masks[0], masks[1], masks[2], masks[3], masks[4], masks[5], int(white), int(black)
    )
    return score if side == WHITE else -score


@njit(cache=False)
def _legal_ep_available(board: np.ndarray, state: np.ndarray) -> bool:
    target, side = int(state[2]), int(state[0])
    if target < 0:
        return False
    captured_square = target - side * 8
    for df in (-1, 1):
        source = target - side * 8 + df
        if not 0 <= source < 64 or abs((source & 7) - (target & 7)) != 1:
            continue
        if board[source] != side * PAWN or board[captured_square] != -side * PAWN:
            continue
        captured = board[captured_square]
        board[source], board[captured_square], board[target] = 0, 0, side * PAWN
        king = -1
        for square in range(64):
            if board[square] == side * KING:
                king = square
                break
        legal = king >= 0 and not _attacked(board, king, -side)
        board[source], board[captured_square], board[target] = side * PAWN, captured, 0
        if legal:
            return True
    return False


@njit(cache=False)
def _position_hash(board: np.ndarray, state: np.ndarray) -> np.uint64:
    """Deterministic position identity; deliberately excludes move counters."""
    value = np.uint64(1469598103934665603)
    for square in range(64):
        value ^= np.uint64(int(board[square]) + 7 + square * 15)
        value *= np.uint64(1099511628211)
    value ^= np.uint64((int(state[0]) + 1) * 17 + int(state[1]) * 31)
    value *= np.uint64(1099511628211)
    ep_square = int(state[2]) if _legal_ep_available(board, state) else -1
    value ^= np.uint64((ep_square + 1) * 67)
    return value


@njit(cache=False)
def _insufficient_material(board: np.ndarray) -> bool:
    minors = 0
    knights = 0
    bishop_color = -1
    for square in range(64):
        kind = abs(int(board[square]))
        if kind in (PAWN, ROOK, QUEEN):
            return False
        if kind in (KNIGHT, BISHOP):
            minors += 1
            if kind == BISHOP:
                color = ((square & 7) + (square >> 3)) & 1
                if bishop_color < 0:
                    bishop_color = color
                elif bishop_color != color:
                    return False
            else:
                knights += 1
    return minors <= 1 or (knights == 0 and bishop_color >= 0)


@njit(cache=False)
def _draw_by_history(
    board: np.ndarray, state: np.ndarray, history: np.ndarray, history_len: int
) -> bool:
    key = _position_hash(board, state)
    matches = 1
    for index in range(history_len):
        if history[index] == key:
            matches += 1
    history[history_len] = key
    return matches >= 3


@njit(cache=False)
def _check_deadline(deadline: float, counters: np.ndarray) -> bool:
    counters[0] += 1
    if counters[0] & 1023:
        return False
    with objmode(now="float64"):
        now = time.monotonic()
    if now >= deadline:
        counters[1] = 1
        return True
    return False


@njit(cache=False)
def _pick_ordered(board: np.ndarray, moves: np.ndarray, start: int, count: int) -> int:
    best_index, best_priority = start, -1
    for index in range(start, count):
        move = int(moves[index])
        target = (move >> 6) & 63
        victim = abs(int(board[target]))
        priority = victim * 16 - abs(int(board[move & 63]))
        if move & EP_FLAG:
            priority = PAWN * 16 - PAWN
        promotion = (move >> 12) & 7
        if promotion:
            priority += 100 + promotion
        if priority > best_priority:
            best_index, best_priority = index, priority
    chosen = int(moves[best_index])
    moves[best_index] = moves[start]
    moves[start] = chosen
    return chosen


@njit(cache=False)
def _pick_search_ordered(
    board: np.ndarray,
    state: np.ndarray,
    moves: np.ndarray,
    start: int,
    count: int,
    quiet_scores: np.ndarray,
) -> int:
    """Try tactical moves first, then quiet moves that caused earlier cutoffs."""
    best_index, best_priority = start, -1
    side_index = int(state[0] == WHITE)
    for index in range(start, count):
        move = int(moves[index])
        source, target = move & 63, (move >> 6) & 63
        victim = abs(int(board[target]))
        promotion = (move >> 12) & 7
        if victim or promotion or move & EP_FLAG:
            if move & EP_FLAG:
                victim = PAWN
            priority = 100_000 + victim * 16 - abs(int(board[source]))
            if promotion:
                priority += 100 + promotion
        else:
            priority = int(quiet_scores[side_index, source, target])
        if priority > best_priority:
            best_index, best_priority = index, priority
    chosen = int(moves[best_index])
    moves[best_index] = moves[start]
    moves[start] = chosen
    return chosen


@njit(cache=False)
def _quiescence(
    board: np.ndarray,
    state: np.ndarray,
    alpha: int,
    beta: int,
    ply: int,
    depth: int,
    deadline: float,
    counters: np.ndarray,
    history: np.ndarray,
    history_len: int,
    tt_keys: np.ndarray,
    tt_moves: np.ndarray,
) -> int:
    if _check_deadline(deadline, counters):
        return 0
    moves = np.empty(256, dtype=np.int64)
    count = _legal_moves(board, state, moves)
    side = int(state[0])
    king = -1
    for square in range(64):
        if board[square] == side * KING:
            king = square
            break
    in_check = _attacked(board, king, -side)
    if count == 0:
        return -100_000 + ply if in_check else 0
    if state[3] >= 100 or _insufficient_material(board):
        return 0
    if _draw_by_history(board, state, history, history_len):
        counters[3] += 1
        return 0
    if ply >= MAX_PLY - 1:
        return _evaluate(board, side)
    if not in_check:
        stand_pat = _evaluate(board, side)
        if stand_pat >= beta:
            return stand_pat
        if stand_pat > alpha:
            alpha = stand_pat
        if depth <= 0:
            return alpha
    for index in range(count):
        move = _pick_ordered(board, moves, index, count)
        target = (move >> 6) & 63
        if not in_check and board[target] == 0 and not move & (EP_FLAG | (7 << 12)):
            # _pick_ordered ranks every capture/EP/promotion above every quiet move.
            # The remaining quiet tail cannot contribute to this non-check search.
            break
        undo = np.empty(10, dtype=np.int64)
        _make(board, state, move, undo)
        score = -_quiescence(
            board,
            state,
            -beta,
            -alpha,
            ply + 1,
            depth - 1,
            deadline,
            counters,
            history,
            history_len + 1,
            tt_keys,
            tt_moves,
        )
        _unmake(board, state, undo)
        if counters[1]:
            return 0
        if score >= beta:
            return score
        if score > alpha:
            alpha = score
    return alpha


@njit(cache=False)
def _negamax(
    board: np.ndarray,
    state: np.ndarray,
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    deadline: float,
    counters: np.ndarray,
    history: np.ndarray,
    history_len: int,
    tt_keys: np.ndarray,
    tt_moves: np.ndarray,
    quiet_scores: np.ndarray,
) -> int:
    if depth <= 0:
        return _quiescence(
            board,
            state,
            alpha,
            beta,
            ply,
            8,
            deadline,
            counters,
            history,
            history_len,
            tt_keys,
            tt_moves,
        )
    if _check_deadline(deadline, counters):
        return 0
    moves = np.empty(256, dtype=np.int64)
    count = _legal_moves(board, state, moves)
    if count == 0:
        side = int(state[0])
        king = -1
        for square in range(64):
            if board[square] == side * KING:
                king = square
                break
        return -100_000 + ply if _attacked(board, king, -side) else 0
    if state[3] >= 100 or _insufficient_material(board):
        return 0
    if _draw_by_history(board, state, history, history_len):
        counters[3] += 1
        return 0
    if ply >= MAX_PLY - 1:
        return _evaluate(board, int(state[0]))
    key = _position_hash(board, state)
    tt_index = int(key & np.uint64(len(tt_keys) - 1))
    preferred = -1
    if tt_keys[tt_index] == key:
        preferred = int(tt_moves[tt_index])
        counters[2] += 1
    best = -101_000
    best_move = -1
    for index in range(count):
        use_preferred = False
        if index == 0 and preferred >= 0:
            for preferred_index in range(count):
                if moves[preferred_index] == preferred:
                    moves[0], moves[preferred_index] = moves[preferred_index], moves[0]
                    use_preferred = True
                    break
        move = (
            int(moves[0]) if use_preferred else
            _pick_search_ordered(board, state, moves, index, count, quiet_scores)
        )
        undo = np.empty(10, dtype=np.int64)
        _make(board, state, move, undo)
        if index == 0:
            score = -_negamax(
                board,
                state,
                depth - 1,
                -beta,
                -alpha,
                ply + 1,
                deadline,
                counters,
                history,
                history_len + 1,
                tt_keys,
                tt_moves,
                quiet_scores,
            )
        else:
            score = -_negamax(
                board,
                state,
                depth - 1,
                -alpha - 1,
                -alpha,
                ply + 1,
                deadline,
                counters,
                history,
                history_len + 1,
                tt_keys,
                tt_moves,
                quiet_scores,
            )
            if alpha < score < beta and not counters[1]:
                score = -_negamax(
                    board,
                    state,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    deadline,
                    counters,
                    history,
                    history_len + 1,
                    tt_keys,
                    tt_moves,
                    quiet_scores,
                )
        _unmake(board, state, undo)
        if counters[1]:
            return 0
        if score > best:
            best = score
            best_move = move
        if score > alpha:
            alpha = score
        if alpha >= beta:
            source, target = move & 63, (move >> 6) & 63
            if board[target] == 0 and not move & (EP_FLAG | (7 << 12)):
                side_index = int(state[0] == WHITE)
                bonus = depth * depth
                quiet_scores[side_index, source, target] = min(
                    16_384, quiet_scores[side_index, source, target] + bonus
                )
            break
    tt_keys[tt_index] = key
    tt_moves[tt_index] = best_move
    return best


@njit(cache=False)
def _root_search(
    board: np.ndarray,
    state: np.ndarray,
    depth: int,
    deadline: float,
    counters: np.ndarray,
    preferred: int,
    history: np.ndarray,
    history_len: int,
    tt_keys: np.ndarray,
    tt_moves: np.ndarray,
) -> tuple[int, int]:
    moves = np.empty(256, dtype=np.int64)
    count = _legal_moves(board, state, moves)
    if count == 0:
        return -1, 0
    best_move, best_score = int(moves[0]), -101_000
    if (
        state[3] >= 100
        or _insufficient_material(board)
        or _draw_by_history(board, state, history, history_len)
    ):
        return best_move, 0
    # Per-root scratch: learned ordering never caches a score or draw outcome.
    quiet_scores = np.zeros((2, 64, 64), dtype=np.int64)
    alpha = -101_000
    for index in range(count):
        use_preferred = False
        if index == 0 and preferred >= 0:
            for preferred_index in range(count):
                if moves[preferred_index] == preferred:
                    moves[0], moves[preferred_index] = moves[preferred_index], moves[0]
                    use_preferred = True
                    break
        move = (
            int(moves[0]) if use_preferred else
            _pick_search_ordered(board, state, moves, index, count, quiet_scores)
        )
        undo = np.empty(10, dtype=np.int64)
        _make(board, state, move, undo)
        if index == 0:
            score = -_negamax(
                board,
                state,
                depth - 1,
                -101_000,
                -alpha,
                1,
                deadline,
                counters,
                history,
                history_len + 1,
                tt_keys,
                tt_moves,
                quiet_scores,
            )
        else:
            score = -_negamax(
                board,
                state,
                depth - 1,
                -alpha - 1,
                -alpha,
                1,
                deadline,
                counters,
                history,
                history_len + 1,
                tt_keys,
                tt_moves,
                quiet_scores,
            )
            if alpha < score < 101_000 and not counters[1]:
                score = -_negamax(
                    board,
                    state,
                    depth - 1,
                    -101_000,
                    -alpha,
                    1,
                    deadline,
                    counters,
                    history,
                    history_len + 1,
                    tt_keys,
                    tt_moves,
                    quiet_scores,
                )
        _unmake(board, state, undo)
        if counters[1]:
            return best_move, 0
        if score > best_score:
            best_move, best_score = move, score
        if score > alpha:
            alpha = score
    return best_move, best_score


compiled_root_search = _root_search


def timed_search(
    source: chess.Board, seconds: float, soft_seconds: float | None = None
) -> tuple[str, int, int]:
    """Iterative search returning move, completed depth and visited nodes."""
    board, state = from_chess(source)
    legal = np.empty(256, dtype=np.int64)
    count = compiled_legal_moves(board, state, legal)
    if count == 0:
        return "0000", 0, 0
    best, depth, total_nodes = int(legal[0]), 0, 0
    started = time.monotonic()
    deadline = started + max(0.0, seconds)
    completed: list[tuple[int, int]] = []
    global LAST_SEARCH_SCORE
    LAST_SEARCH_SCORE = None
    history = np.zeros(256, dtype=np.uint64)
    history_len = _seed_history(source, history)
    tt_keys = np.zeros(TT_LIMIT, dtype=np.uint64)
    tt_moves = np.full(TT_LIMIT, -1, dtype=np.int64)
    for candidate_depth in range(1, 64):
        counters = np.zeros(4, dtype=np.int64)
        candidate, score = compiled_root_search(
            board,
            state,
            candidate_depth,
            deadline,
            counters,
            best,
            history,
            history_len,
            tt_keys,
            tt_moves,
        )
        total_nodes += int(counters[0])
        if counters[1]:
            break
        best, depth = candidate, candidate_depth
        LAST_SEARCH_SCORE = int(score)
        completed.append((int(best), int(score)))
        if soft_seconds is not None:
            elapsed = time.monotonic() - started
            stable = (
                depth >= 4 and len(completed) >= 3
                and len({row[0] for row in completed[-3:]}) == 1
                and max(row[1] for row in completed[-3:])
                - min(row[1] for row in completed[-3:]) <= 30
            )
            # The soft threshold is checked ONLY between complete iterations.
            # A newly started iteration may finish up to the hard deadline.
            allowance = soft_seconds * (0.65 if stable else 1.0)
            if elapsed >= allowance or abs(score) >= 99_000:
                break
    return move_to_uci(best), depth, total_nodes


def fixed_score(source: chess.Board, depth: int) -> int:
    """Test helper for terminal, history, and fixed-depth score semantics."""
    board, state = from_chess(source)
    history = np.zeros(256, dtype=np.uint64)
    history_len = _seed_history(source, history)
    counters = np.zeros(4, dtype=np.int64)
    tt_keys = np.zeros(TT_LIMIT, dtype=np.uint64)
    tt_moves = np.full(TT_LIMIT, -1, dtype=np.int64)
    return int(
        _negamax(
            board,
            state,
            depth,
            -101_000,
            101_000,
            0,
            time.monotonic() + 10,
            counters,
            history,
            history_len,
            tt_keys,
            tt_moves,
            np.zeros((2, 64, 64), dtype=np.int64),
        )
    )


_previous_board: chess.Board | None = None


def _restore_history(fen: str) -> chess.Board:
    incoming = chess.Board(fen)
    if _previous_board is None:
        return incoming
    previous = _previous_board
    if previous.turn == incoming.turn or incoming.ply() != previous.ply() + 1:
        return incoming
    target = incoming.fen()
    for move in list(previous.legal_moves):
        previous.push(move)
        if previous.fen() == target:
            return previous
        previous.pop()
    return incoming


def _legacy_get_move(fen: str, time_left_ms: int) -> str:
    """Return a legal move with parsing and response overhead outside the search budget."""
    global _previous_board

    started = time.monotonic()
    incoming = chess.Board(fen)
    legal = list(incoming.legal_moves)
    if not legal:
        return "0000"
    remaining = max(0, time_left_ms) / 1000.0
    reserve = max(0.01, min(0.25, remaining * 0.15))
    budget = min(2.5, remaining / 35.0, max(0.0, remaining - reserve))
    move = legal[0]
    global LAST_SEARCH_DEPTH
    LAST_SEARCH_DEPTH = 0
    if budget >= 0.02:
        source = _restore_history(fen)
        search_budget = max(0.0, budget - (time.monotonic() - started))
        uci, LAST_SEARCH_DEPTH, _ = timed_search(source, search_budget)
        move = chess.Move.from_uci(uci)
        if move not in incoming.legal_moves:
            move = legal[0]
        source.push(move)
        _previous_board = source
    else:
        incoming.push(move)
        _previous_board = incoming
    return move.uci()


USE_COMPLETION_TIME = True
LAST_SEARCH_SCORE: int | None = None
LAST_SEARCH_NODES = 0
LAST_BUDGETS = (0.0, 0.0)
_BUILD_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:8]
_diagnostic_bytes = 0


def _time_budgets(source: chess.Board, remaining: float, legal_count: int) -> tuple[float, float]:
    """Phase estimate plus 0.5s increment; bounded soft and hard wall-clock budgets."""
    reserve = max(0.01, min(0.25, remaining * 0.15))
    safe = max(0.0, remaining - reserve)
    if remaining <= 3.0:
        hard = min(safe, remaining * 0.20, remaining / 35.0 + min(0.05, remaining * 0.05))
        return hard, hard
    moves_to_go = max(24, min(44, 18 + len(source.piece_map())))
    complexity = 1.15 if source.is_check() else (1.10 if legal_count >= 35 else 1.0)
    normal = ((remaining - reserve) / moves_to_go + 0.5 * 0.70) * complexity
    hard = min(8.0, normal * 2.25, remaining * 0.12, safe)
    return min(normal, hard), hard


def get_move(fen: str, time_left_ms: int) -> str:
    """Preserve complete-iteration answers and observed history under a hard deadline."""
    if not USE_COMPLETION_TIME:
        return _legacy_get_move(fen, time_left_ms)
    global _previous_board, LAST_SEARCH_DEPTH, LAST_SEARCH_NODES, LAST_SEARCH_SCORE
    global LAST_BUDGETS, _diagnostic_bytes
    started = time.monotonic()
    source = _restore_history(fen)
    legal = list(source.legal_moves)
    LAST_SEARCH_DEPTH, LAST_SEARCH_NODES, LAST_SEARCH_SCORE = 0, 0, None
    if not legal:
        return "0000"
    soft, hard = _time_budgets(source, max(0, time_left_ms) / 1000.0, len(legal))
    LAST_BUDGETS = soft, hard
    move = legal[0]
    overhead = time.monotonic() - started
    if len(legal) > 1 and hard - overhead >= 0.02:
        uci, LAST_SEARCH_DEPTH, LAST_SEARCH_NODES = timed_search(
            source, max(0.0, hard - overhead), max(0.0, soft - overhead)
        )
        proposed = chess.Move.from_uci(uci)
        if proposed in legal:
            move = proposed
    source.push(move)
    _previous_board = source
    # Keep the whole game's diagnostic output below the platform's 8KiB limit.
    elapsed = time.monotonic() - started
    line = (f"{_BUILD_SHA} d{LAST_SEARCH_DEPTH} n{LAST_SEARCH_NODES} "
            f"s{LAST_SEARCH_SCORE} t{elapsed:.3f} b{soft:.2f}/{hard:.2f}\n")
    if _diagnostic_bytes + len(line) <= 7000:
        print(line, end="", file=sys.stderr)
        _diagnostic_bytes += len(line)
    return move.uci()


def _seed_history(source: chess.Board, output: np.ndarray) -> int:
    positions: list[chess.Board] = []
    cursor = source.copy(stack=True)
    while cursor.move_stack and cursor.halfmove_clock > 0:
        cursor.pop()
        positions.append(cursor.copy(stack=False))
    positions.reverse()
    for index, position in enumerate(positions):
        board, state = from_chess(position)
        output[index] = _position_hash(board, state)
    return len(positions)


LAST_SEARCH_DEPTH = 0


_search_counters = np.zeros(4, dtype=np.int64)
_search_history = np.zeros(256, dtype=np.uint64)
_search_tt_keys = np.zeros(TT_LIMIT, dtype=np.uint64)
_search_tt_moves = np.full(TT_LIMIT, -1, dtype=np.int64)
compiled_root_search(
    _warm_board,
    _warm_state,
    1,
    time.monotonic() + 30,
    _search_counters,
    -1,
    _search_history,
    0,
    _search_tt_keys,
    _search_tt_moves,
)
SEARCH_WARMUP_SECONDS = time.monotonic() - _started - WARMUP_SECONDS

"""Public opening patterns for local tests, never shipped as an opening book."""

import chess

OPENINGS = {
    "ruy_lopez": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6",
    "sicilian": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
    "french": "e4 e6 d4 d5 Nc3 Nf6 e5 Nfd7 f4 c5 Nf3",
    "caro_kann": "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6",
    "queens_gambit": "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3",
    "slav": "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5",
    "kings_indian": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5",
    "english": "c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5 Bg2 Nb6",
    "scotch": "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5 Be3 Qf6 c3 Nge7",
    "italian": "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O",
}


HOLDOUT_OPENINGS = {
    "petroff": "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3 Nc6 O-O Be7",
    "vienna": "e4 e5 Nc3 Nf6 Bc4 Nc6 d3 Bc5 Nf3 d6 O-O O-O",
    "pirc": "e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 O-O Nf3 c6",
    "scandinavian": "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6 Bc4 Bf5",
    "catalan": "d4 Nf6 c4 e6 g3 d5 Bg2 Be7 Nf3 O-O O-O dxc4 Qc2 a6",
    "queens_indian": "d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O Nc3 Ne4",
    "tarrasch": "d4 d5 c4 e6 Nc3 c5 cxd5 exd5 Nf3 Nc6 g3 Nf6 Bg2 Be7",
    "reti": "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 d3 O-O Nbd2 c5 e4 Nc6",
    "four_knights": "e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4 O-O O-O d3 d6",
    "english_symmetrical": "c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 Nf3 Nf6 O-O O-O d4 cxd4 Nxd4",
}


CONFIRMATION_OPENINGS = {
    "london": "d4 d5 Nf3 Nf6 Bf4 c5 e3 Nc6 c3 e6 Nbd2 Bd6",
    "colle": "d4 d5 Nf3 Nf6 e3 e6 Bd3 c5 c3 Nc6 Nbd2 Bd6 O-O O-O",
    "dutch": "d4 f5 c4 Nf6 g3 e6 Bg2 Be7 Nf3 O-O O-O d6 Nc3 Qe8",
    "benoni": "d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6 e4 g6 Nf3 Bg7",
    "alekhine": "e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4 Be2 e6 O-O Be7",
    "closed_sicilian": "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6 f4 e6",
    "french_tarrasch": "e4 e6 d4 d5 Nd2 c5 exd5 exd5 Ngf3 Nc6 Bb5 Bd6",
    "caro_advance": "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6",
    "nimzo_indian": "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5 Nf3 c5 O-O Nc6",
    "grunfeld": "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7 Nf3 c5",
}


def positions(suite: str = "development") -> list[tuple[str, str]]:
    suites = {
        "development": OPENINGS,
        "holdout": HOLDOUT_OPENINGS,
        "confirmation": CONFIRMATION_OPENINGS,
    }
    if suite not in suites:
        raise ValueError(f"Unknown position suite: {suite}")
    result = []
    for name, line in suites[suite].items():
        board = chess.Board()
        for move in line.split():
            board.push_san(move)
        result.append((name, board.fen()))
    return result

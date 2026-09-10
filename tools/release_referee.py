"""2026-09-10 rule adapter; keep the historical harness and results unchanged.

Source: https://aichessathon.com/docs/agent-contract.md and /docs/rules.md.
The original protocol runner is reused. At 600 total plies the result is a draw,
including opening plies; initialization has 90 seconds. Observable repetition and
fifty-move history start at the supplied FEN. Flag fall draws only when the other
side has insufficient mating material according to python-chess.
"""

import time
from collections.abc import Callable
from typing import Any

import chess

from harness.referee import Outcome, _decide, _legal_move, _opponent_wins, _outcome
from harness.sandbox import Agent, AgentFailure


def play_match(
    white: Agent,
    black: Agent,
    base_ms: int,
    increment_ms: int,
    ply_cap: int = 600,
    start_fen: str = chess.STARTING_FEN,
    record: Callable[[dict[str, Any]], None] | None = None,
) -> Outcome:
    board = chess.Board(start_fen)
    rule_board = chess.Board(start_fen)
    rule_board.halfmove_clock = 0
    agents = {chess.WHITE: white, chess.BLACK: black}
    try:
        failures = {}
        for color, player in agents.items():
            try:
                player.start(90)
            except AgentFailure as failure:
                failures[color] = failure.reason
        if len(failures) == 2:
            return _outcome(board, "void", "both_failed")
        if failures:
            color = next(iter(failures))
            return _outcome(board, _opponent_wins(color), failures[color])
        clock = {chess.WHITE: float(base_ms), chess.BLACK: float(base_ms)}
        while True:
            finish = rule_board.outcome(claim_draw=True)
            if finish is not None:
                return _outcome(board, _decide(finish), finish.termination.name.lower())
            if board.ply() >= ply_cap:
                return _outcome(board, "draw", "ply_cap_draw")
            mover = board.turn
            before = clock[mover]
            started = time.monotonic()
            failure_reason = None
            uci = None
            try:
                uci = agents[mover].move(board.fen(), int(before))
            except AgentFailure as failure:
                failure_reason = failure.reason
            elapsed_ms = (time.monotonic() - started) * 1000
            clock[mover] -= elapsed_ms
            if clock[mover] < 0 and failure_reason is None:
                failure_reason = "flag"
            move = None if uci is None else _legal_move(board, uci)
            if failure_reason is None and move is None:
                failure_reason = "illegal"
            if failure_reason is None:
                assert move is not None
                board.push(move)
                rule_board.push(move)
                clock[mover] += increment_ms
            if record is not None:
                record({"event": "clock", "side": "white" if mover else "black",
                        "before_ms": before, "charged_ms": elapsed_ms,
                        "after_ms": clock[mover], "increment_ms": increment_ms,
                        "accepted": failure_reason is None, "failure": failure_reason,
                        "total_plies": board.ply()})
            if failure_reason is not None:
                winner = _opponent_wins(mover)
                if failure_reason == "flag" and board.has_insufficient_material(not mover):
                    return _outcome(board, "draw", "flag")
                return _outcome(board, winner, failure_reason)
    finally:
        white.stop()
        black.stop()

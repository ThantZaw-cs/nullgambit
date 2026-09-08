"""Audit private online PGN/LOG pairs and search from their real game histories.

Outputs default to the ignored online data directory. No opening moves before the
PGN's starting FEN are invented. Our own engine's scores are diagnostics, not an oracle.
"""

import argparse
import csv
import hashlib
import importlib
import json
import platform
import re
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import chess
import chess.pgn
import numpy as np


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def field(text: str, label: str) -> str:
    match = re.search(r"^  " + re.escape(label) + r"\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def read_games(directory: Path) -> list[tuple[dict[str, Any], chess.pgn.Game]]:
    """Deduplicate by match ID, falling back to round/date/players/start FEN."""
    logs: dict[str, list[tuple[Path, str]]] = {}
    for path in sorted(directory.glob("*.log")):
        text = path.read_text()
        round_text = field(text, "Round").removeprefix("Rated ")
        if round_text:
            logs.setdefault(round_text, []).append((path, text))
    result: list[tuple[dict[str, Any], chess.pgn.Game]] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.glob("*.pgn")):
        with path.open() as handle:
            while (game := chess.pgn.read_game(handle)) is not None:
                if game.errors:
                    raise ValueError(f"PGN errors in {path}: {game.errors}")
                board = game.board()
                assert board.is_valid(), path
                round_number = game.headers.get("Round", "?")
                candidates = [
                    (p, t) for p, t in logs.get(round_number, [])
                    if field(t, "Start FEN") == board.fen()
                    and field(t, "Opponent") in (game.headers["White"], game.headers["Black"])
                ]
                identities = {field(t, "Match ID") for _, t in candidates}
                if len(identities) > 1:
                    raise ValueError(f"Ambiguous match logs for {path}")
                log_path, log_text = candidates[0] if candidates else (None, "")
                match_id = field(log_text, "Match ID")
                key = match_id or "|".join(
                    game.headers.get(k, "?") for k in ("Date", "Round", "White", "Black", "FEN")
                )
                line = " ".join(m.uci() for m in game.mainline_moves())
                fingerprint = hashlib.sha256((board.fen() + line).encode()).hexdigest()
                if key in seen:
                    if seen[key] != fingerprint:
                        raise ValueError(f"Conflicting duplicate match {key}")
                    continue
                seen[key] = fingerprint
                our_color = game.headers["White"] == "NullGambit"
                assert "NullGambit" in (game.headers["White"], game.headers["Black"])
                move_logs = re.findall(
                    r"^\s+(\d+)\s+(\S+)\s+([\d.]+) s\s+([\d.]+) s$",
                    log_text, re.MULTILINE,
                )
                clocks = {chess.WHITE: 120.0, chess.BLACK: 120.0}
                own_index = 0
                moves: list[dict[str, Any]] = []
                for ply, node in enumerate(game.mainline()):
                    move = node.move
                    assert move is not None and move in board.legal_moves
                    mover = board.turn
                    san = board.san(move)
                    after = node.clock()
                    before = clocks[mover]
                    row: dict[str, Any] = {
                        "ply_from_start": ply, "fullmove": board.fullmove_number,
                        "side": "white" if mover else "black", "ours": mover == our_color,
                        "fen": board.fen(), "san": san, "uci": move.uci(),
                        "clock_before_s": before, "clock_after_s": after,
                        "elapsed_s": None if after is None else before + 0.5 - after,
                        "history_plies": len(board.move_stack),
                        "is_repetition_2": board.is_repetition(2),
                        "can_claim_threefold": board.can_claim_threefold_repetition(),
                    }
                    if mover == our_color:
                        if move_logs:
                            num, logged_san, elapsed, clock = move_logs[own_index]
                            assert int(num) == own_index + 1 and logged_san == san, (path, row)
                            assert after is not None and abs(float(clock) - after) <= 0.051
                            assert abs(float(elapsed) - (before + 0.5 - after)) <= 0.101
                            row["log_elapsed_s"] = float(elapsed)
                        own_index += 1
                    moves.append(row)
                    if after is not None:
                        clocks[mover] = after
                    board.push(move)
                if move_logs:
                    assert len(move_logs) == own_index
                outcome = board.outcome(claim_draw=True)
                metadata: dict[str, Any] = {
                    "key": key, "match_id": match_id or None, "round": round_number,
                    "pgn": str(path), "pgn_sha256": sha256(path),
                    "log": str(log_path) if log_path else None,
                    "log_sha256": sha256(log_path) if log_path else None,
                    "headers": dict(game.headers), "start_fen": game.board().fen(),
                    "version": "unknown", "version_hint": "unknown",
                    "version_reason": "No per-match submission hash/ID in supplied logs",
                    "our_moves": own_index, "plies": len(moves),
                    "replayed_result": outcome.result() if outcome else None,
                    "replayed_termination": outcome.termination.name if outcome else None,
                    "moves": moves,
                }
                if outcome:
                    assert outcome.result() == game.headers["Result"]
                result.append((metadata, game))
    return result


def search(
    module: ModuleType, source: chess.Board, seconds: float, max_depth: int = 63,
) -> dict[str, Any]:
    """Same iterative-deepening loop as the submitted entry, with score telemetry."""
    board, state = module.from_chess(source)
    legal = np.empty(256, dtype=np.int64)
    count = module.compiled_legal_moves(board, state, legal)
    assert count > 0
    best, depth, score, total_nodes = int(legal[0]), 0, None, 0
    history = np.zeros(256, dtype=np.uint64)
    history_len = module._seed_history(source, history)
    keys = np.zeros(module.TT_LIMIT, dtype=np.uint64)
    tt_moves = np.full(module.TT_LIMIT, -1, dtype=np.int64)
    started = time.monotonic()
    iterations = []
    for candidate_depth in range(1, max_depth + 1):
        counters = np.zeros(4, dtype=np.int64)
        candidate, candidate_score = module.compiled_root_search(
            board, state, candidate_depth, started + seconds, counters, best,
            history, history_len, keys, tt_moves,
        )
        total_nodes += int(counters[0])
        if counters[1]:
            break
        best, depth, score = candidate, candidate_depth, candidate_score
        iterations.append({"depth": depth, "score_cp": int(score),
                           "move": module.move_to_uci(best), "nodes": int(counters[0])})
    return {"move": module.move_to_uci(best), "depth": depth,
            "score_cp": score, "nodes": total_nodes, "elapsed_s": time.monotonic() - started,
            "iterations": iterations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/online/2026-09-08"))
    parser.add_argument("--search-rounds", nargs="*", default=[])
    parser.add_argument("--seconds", type=float, default=2.5)
    parser.add_argument("--max-own-moves", type=int, default=38)
    parser.add_argument("--module", default="baselines.online_v3.agent")
    args = parser.parse_args()
    output = args.directory / "derived"
    output.mkdir(exist_ok=True)
    games = read_games(args.directory)
    summary = list(csv.DictReader((args.directory / "aichessathon-games.csv").open()))
    unique_summary: dict[str, dict[str, str]] = {}
    for row in summary:
        key = row["round"]
        if key in unique_summary and unique_summary[key] != row:
            raise ValueError(f"Conflicting summary rows for {key}")
        unique_summary[key] = row
    linked_rounds = {"Rated " + metadata["round"] for metadata, _ in games}
    for metadata, _ in games:
        linked = unique_summary.get("Rated " + metadata["round"])
        metadata["summary"] = linked
        if linked is not None:
            opponent = metadata["headers"]["Black"] if linked["colour"] == "White" else (
                metadata["headers"]["White"]
            )
            assert linked["opponent"] == opponent
            assert int(linked["moves"]) == metadata["our_moves"]
    summary_records = []
    for row in unique_summary.values():
        summary_records.append({**row, "version": "unknown", "version_hint": "unknown",
                                "pgn_log_available": row["round"] in linked_rounds})
    report = {
        "platform": platform.platform(), "summary_rows": len(summary),
        "unique_summary_rounds": len(unique_summary),
        "summary": summary_records,
        "version_note": "No supplied per-game submission ID/hash. Neither initialization "
        "duration nor finishing time identifies the source version.",
        "games": [metadata for metadata, _ in games],
    }
    (output / "intake.json").write_text(json.dumps(report, indent=2) + "\n")
    print([(m["round"], m["our_moves"], m["replayed_termination"]) for m, _ in games], flush=True)
    if not args.search_rounds:
        return
    module = importlib.import_module(args.module)
    assert module.__file__ is not None
    diagnostics: dict[str, Any] = {
        "engine_sha256": sha256(Path(module.__file__)), "seconds": args.seconds,
        "platform": platform.platform(), "positions": [],
    }
    diagnostic_path = output / f"scan-{args.module}-{args.seconds}.json"
    for metadata, game in sorted(games, key=lambda pair: {"58": 0, "60": 1, "54": 2}.get(
        pair[0]["round"], 3
    )):
        if metadata["round"] not in args.search_rounds:
            continue
        board = game.board()
        own_index = 0
        for row in metadata["moves"]:
            if row["ours"] and own_index < args.max_own_moves:
                own_index += 1
                searched = search(module, board, args.seconds)
                record = {"round": metadata["round"], "own_index": own_index,
                          "position": row, "search": searched}
                diagnostics["positions"].append(record)
                print(metadata["round"], own_index, row["fullmove"], row["san"],
                      searched["move"], searched["depth"], searched["score_cp"], flush=True)
                diagnostic_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
            board.push_uci(row["uci"])


if __name__ == "__main__":
    main()

"""Compare observed choices at common completed depth, using our own evaluator only."""

import argparse
import importlib
import json
import time
from pathlib import Path
from typing import Any

import chess
import numpy as np

from tools.online_review import search, sha256
from tools.validate_v4 import BASELINE_SHA256, CANDIDATE_SHA256


def choice_score(
    module: Any, source: chess.Board, uci: str, depth: int, seconds: float
) -> dict[str, Any]:
    child = source.copy(stack=True)
    child.push_uci(uci)
    board, state = module.from_chess(child)
    history = np.zeros(256, dtype=np.uint64)
    history_len = module._seed_history(child, history)
    counters = np.zeros(4, dtype=np.int64)
    started = time.monotonic()
    arguments: tuple[Any, ...] = (
        board,
        state,
        depth - 1,
        -101_000,
        101_000,
        1,
        started + seconds,
        counters,
        history,
        history_len,
        np.zeros(module.TT_LIMIT, dtype=np.uint64),
        np.full(module.TT_LIMIT, -1, dtype=np.int64),
    )
    if hasattr(module, "_pick_search_ordered"):
        arguments += (np.zeros((2, 64, 64), dtype=np.int64),)
    score = -int(module._negamax(*arguments))
    return {
        "score_cp": score if not counters[1] else None,
        "aborted": bool(counters[1]),
        "nodes": int(counters[0]),
        "elapsed_s": time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--versions", nargs="+", default=["v4"])
    parser.add_argument("--select", nargs="*")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--choice-plan", type=Path, help="Predeclared common-depth branch probes")
    args = parser.parse_args()
    if args.out.exists():
        raise RuntimeError("Refusing to overwrite earlier diagnostic evidence")
    modules = {v: importlib.import_module(f"baselines.online_{v}.agent") for v in args.versions}
    for version, module in modules.items():
        expected = {"v3": BASELINE_SHA256, "v4": CANDIDATE_SHA256}[version]
        assert module.__file__ is not None
        assert sha256(Path(module.__file__)) == expected
    scan = json.loads(args.scan.read_text())["positions"]
    if args.choice_plan is not None:
        plan = json.loads(args.choice_plan.read_text())
        cross: dict[str, Any] = {
            "note": plan["note"],
            "seconds_per_choice_cap": plan["seconds_per_choice_cap"],
            "cases": [],
        }
        positions = {row["key"]: row for row in scan}
        for case in plan["cases"]:
            item = positions[case["key"]]
            source = chess.Board(item["start_fen"])
            for uci in item["history"]:
                source.push_uci(uci)
            assert source.fen() == item["position"]["fen"]
            entry = {**case, "scores": {}}
            for version, module in modules.items():
                entry["scores"][version] = {}
                for uci in case["moves"]:
                    score = choice_score(
                        module, source, uci, case["depth"], plan["seconds_per_choice_cap"]
                    )
                    entry["scores"][version][uci] = score
                    print(case["key"], version, case["depth"], uci, score, flush=True)
            cross["cases"].append(entry)
            args.out.write_text(json.dumps(cross, indent=2) + "\n")
        return
    report: dict[str, Any] = {
        "depth": args.depth,
        "seconds_per_search_cap": args.seconds,
        "note": "Extra budget is diagnostic only, not the deployed clock "
        "policy. Own-engine deep scores are not ground truth.",
        "positions": [],
    }
    for item in scan:
        if args.select is not None and item["key"] not in args.select:
            continue
        source = chess.Board(item["start_fen"])
        for uci in item["history"]:
            source.push_uci(uci)
        assert source.fen() == item["position"]["fen"]
        choices = {item["position"]["uci"]} | {r["move"] for r in item["runs"]}
        row: dict[str, Any] = {
            "key": item["key"],
            "online": item["position"]["san"],
            "online_uci": item["position"]["uci"],
            "versions": {},
        }
        for label, module in modules.items():
            root = search(module, source, args.seconds, args.depth)
            measured: dict[str, Any] = {
                "root": root,
                "choices": {},
                "comparison_depth": root["depth"],
                "requested_depth_reached": root["depth"] == args.depth,
            }
            if root["depth"] > 0:
                for uci in sorted(choices | {root["move"]}):
                    score = (
                        {
                            "score_cp": root["score_cp"],
                            "aborted": False,
                            "note": "completed root optimum",
                        }
                        if uci == root["move"]
                        else choice_score(module, source, uci, root["depth"], args.seconds)
                    )
                    measured["choices"][uci] = {
                        "san": source.san(chess.Move.from_uci(uci)),
                        **score,
                    }
            row["versions"][label] = measured
            print(
                item["key"],
                "online",
                row["online"],
                label,
                "depth",
                root["depth"],
                "best",
                root["move"],
                root["score_cp"],
                {v["san"]: v["score_cp"] for v in measured["choices"].values()},
                flush=True,
            )
        report["positions"].append(row)
        args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

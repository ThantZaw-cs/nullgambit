"""Small, checkpointed v4 efficiency comparison on existing regression positions."""

import argparse
import importlib
import json
import math
import random
import signal
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess
import numpy as np

from tools.online_review import sha256
from tools.positions import OPENINGS
from tools.release_environment import environment
from tools.search_decisions import probe

ROOT = Path(__file__).resolve().parents[1]
V4_HASH = "7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4"


def sources() -> list[tuple[str, chess.Board]]:
    result = []
    for name, line in OPENINGS.items():
        board = chess.Board()
        for san in line.split():
            board.push_san(san)
        result.append((name, board))
    path = ROOT / "benchmarks/astra-v4-diagnosis/slav-mac-probes.json"
    for row in json.loads(path.read_text())["positions"]:
        board = chess.Board(row["start_fen"])
        for move in row["history"]:
            board.push_uci(move)
        assert board.fen() == row["position"]["fen"]
        result.append((row["key"], board))
    return result


def fixed(module: Any, source: chess.Board, depth: int) -> dict[str, Any]:
    board, state = module.from_chess(source)
    original = board.copy(), state.copy()
    history = np.zeros(256, dtype=np.uint64)
    length = module._seed_history(source, history)
    prefix = history[:length].copy()
    keys = np.zeros(module.TT_LIMIT, dtype=np.uint64)
    moves = np.full(module.TT_LIMIT, -1, dtype=np.int64)
    best = -1
    rows = []
    started = time.monotonic()
    for current in range(1, depth + 1):
        counts = np.zeros(4, dtype=np.int64)
        args = (board, state, current, time.monotonic() + 20, counts, best,
                history, length, keys, moves)
        tick = time.monotonic()
        best, score = module.compiled_root_search(*args)
        elapsed = time.monotonic() - tick
        assert not counts[1], "Fixed-depth deadline reached; retain failed stage"
        rows.append({"depth": current, "move": module.move_to_uci(int(best)),
                     "score": int(score), "nodes": int(counts[0]), "elapsed_s": elapsed})
    elapsed = time.monotonic() - started
    assert np.array_equal(board, original[0]) and np.array_equal(state, original[1])
    assert np.array_equal(history[:length], prefix)
    return {"iterations": rows, "elapsed_s": elapsed, "depth": depth,
            "nodes": sum(r["nodes"] for r in rows), "restored": True}


def stop(_signum: int, _frame: Any) -> None:
    raise TimeoutError("Predeclared stage wall limit")


def summarize(directory: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in (directory / "runs.jsonl").read_text().splitlines()]
    stage = json.loads((directory / "stage.json").read_text())
    assert stage["status"] == "completed" and len(rows) == stage["expected_rows"]
    per_position = []
    for name, _ in sources():
        fixed_rows = [r for r in rows if r["kind"] == "fixed" and r["id"] == name]
        latencies = {label: [r["elapsed_s"] for r in fixed_rows if r["label"] == label]
                     for label in ("v4", "candidate")}
        medians = {k: statistics.median(v) for k, v in latencies.items()}
        old = next(r for r in fixed_rows if r["label"] == "v4")
        new = next(r for r in fixed_rows if r["label"] == "candidate")
        for measured in fixed_rows:
            assert [(r["move"], r["score"], r["nodes"]) for r in measured["iterations"]] == [
                (r["move"], r["score"], r["nodes"]) for r in old["iterations"]
            ], (name, measured["label"], measured["repeat"])
        per_position.append({
            "id": name, "median_elapsed_s": medians,
            "latency_ratio": medians["candidate"] / medians["v4"],
            "nodes_ratio": new["nodes"] / old["nodes"],
            "v4_median_absolute_deviation_fraction": statistics.median(
                abs(t - medians["v4"]) for t in latencies["v4"]) / medians["v4"],
            "same_scores": [r["score"] for r in old["iterations"]]
                           == [r["score"] for r in new["iterations"]],
            "same_moves": [r["move"] for r in old["iterations"]]
                          == [r["move"] for r in new["iterations"]],
        })
    logs = [math.log(p["latency_ratio"]) for p in per_position]
    rng = random.Random(20260910)
    boot = sorted(math.exp(statistics.mean(rng.choices(logs, k=len(logs)))) for _ in range(10000))
    timed = [r for r in rows if r["kind"] == "timed"]
    pairs: dict[tuple[str, int], dict[str, Any]] = {}
    for row in timed:
        pairs.setdefault((row["id"], row["repeat"]), {})[row["label"]] = row
    depth_diffs = [v["candidate"]["depth"] - v["v4"]["depth"] for v in pairs.values()]
    result: dict[str, Any] = {
        "stage_status": stage["status"], "rows": len(rows), "positions": per_position,
        "all_fixed_repeats_same_moves_scores_nodes": True,
        "geometric_mean_latency_ratio": math.exp(statistics.mean(logs)),
        "latency_ratio_bootstrap_95": [boot[250], boot[9749]],
        "worst_latency_ratio": max(p["latency_ratio"] for p in per_position),
        "median_noise_fraction": statistics.median(
            p["v4_median_absolute_deviation_fraction"] for p in per_position),
        "geometric_mean_nodes_ratio": math.exp(statistics.mean(
            math.log(p["nodes_ratio"]) for p in per_position)),
        "timed_pairs": len(pairs),
        "timed_depth_higher_equal_lower": [sum(d > 0 for d in depth_diffs),
                                          sum(d == 0 for d in depth_diffs),
                                          sum(d < 0 for d in depth_diffs)],
        "timed_different_moves": sum(v["candidate"]["move"] != v["v4"]["move"]
                                     for v in pairs.values()),
        "timed_all_legal_clock_history_unmake": all(
            r["within_clock"] and r["history_verified"] and r["unmake_verified"] for r in timed),
        "maximum_timed_elapsed_s": max((r["elapsed_s"] for r in timed), default=0),
        "note": "Position bootstrap describes this seen sample; no strength inference. "
                "Nodes include all completed and aborted work. Import/compile is excluded.",
    }
    result["performance_gate_passed"] = (
        result["geometric_mean_latency_ratio"] <= 0.97 and boot[9749] < 1.0)
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--clock-ms", type=int, default=10000)
    parser.add_argument("--timed-repeats", type=int, default=3)
    parser.add_argument("--limit-s", type=int, default=300)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    metadata: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(), "status": "running",
        "environment": environment(), "parameters": vars(args) | {"out": str(args.out)},
        "scope": "14 previously seen ordinary/Slav regressions, not unseen validation",
        "order": "alternating per position/repeat, same process, sequential, warm first",
        "completed_rows": 0, "modules": {},
    }
    path = args.out / "stage.json"
    path.write_text(json.dumps(metadata, indent=2) + "\n")
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(args.limit_s)
    try:
        modules = {}
        for label, name, digest in (("v4", "baselines.online_v4.agent", V4_HASH),
                                    ("candidate", args.candidate, args.sha256)):
            tick = time.monotonic()
            module = importlib.import_module(name)
            import_s = time.monotonic() - tick
            assert module.__file__ is not None
            assert sha256(Path(module.__file__)) == digest
            modules[label] = module
            metadata["modules"][label] = {
                "name": name, "file": str(Path(module.__file__).resolve()), "sha256": digest,
                "import_including_compile_s": import_s,
                "search_warmup_s": module.SEARCH_WARMUP_SECONDS,
                "root_signatures": [str(s) for s in module.compiled_root_search.signatures],
                "root_implementation_file": (
                    module.compiled_root_search.py_func.__code__.co_filename
                ),
            }
        boards = sources()
        metadata["expected_rows"] = len(boards) * 2 * (args.repeats + args.timed_repeats)
        # Warm every fixed-depth case on both implementations, outside measurements.
        warm_started = time.monotonic()
        for _, board in boards:
            for module in modules.values():
                fixed(module, board, args.depth)
        metadata["additional_warmup_s"] = time.monotonic() - warm_started
        path.write_text(json.dumps(metadata, indent=2) + "\n")
        with (args.out / "runs.jsonl").open("x") as output:
            for kind, repeats in (("fixed", args.repeats), ("timed", args.timed_repeats)):
                for index, (name, board) in enumerate(boards):
                    for repeat in range(repeats):
                        labels = ["v4", "candidate"]
                        if (index + repeat) % 2:
                            labels.reverse()
                        for label in labels:
                            result = (fixed(modules[label], board, args.depth) if kind == "fixed"
                                      else probe(modules[label], board, args.clock_ms))
                            row = {"kind": kind, "id": name, "repeat": repeat,
                                   "label": label, **result}
                            output.write(json.dumps(row) + "\n")
                            output.flush()
                            metadata["completed_rows"] += 1
                    path.write_text(json.dumps(metadata, indent=2) + "\n")
                    print(kind, name, metadata["completed_rows"], flush=True)
        assert metadata["completed_rows"] == metadata["expected_rows"]
        metadata["status"] = "completed"
        metadata["exit_code"] = 0
    except BaseException as error:
        metadata.update(status="incomplete", error=f"{type(error).__name__}: {error}", exit_code=1)
        raise
    finally:
        signal.alarm(0)
        metadata["finished_utc"] = datetime.now(UTC).isoformat()
        metadata["elapsed_s"] = time.monotonic() - started
        path.write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()

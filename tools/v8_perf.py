"""Warm, rotating four-way fixed-depth search comparison on existing regressions."""

import argparse
import importlib
import json
import math
import signal
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess
import numpy as np

from tools.online_review import sha256
from tools.qsearch_bench import sources, stop
from tools.release_environment import environment
from tools.v8_match import V7_SHA256, checkpoint

CONFIGS = {"v7": (False, False), "tt": (True, False), "lmr": (False, True), "both": (True, True)}
COUNTERS = (
    "nodes",
    "aborted",
    "move_hits",
    "repetitions",
    "tt_probes",
    "tt_hits",
    "tt_cutoffs",
    "tt_context_rejects",
    "tt_stores",
    "lmr_reductions",
    "lmr_researches",
    "lmr_full_window",
    "reserved12",
    "reserved13",
    "reserved14",
    "reserved15",
)


def fixed_search(
    module: Any,
    source: chess.Board,
    depth: int,
    use_tt: bool = False,
    use_lmr: bool = False,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Same D1..D progression and fresh tables; measure allocations and all iterations."""
    started = time.monotonic()
    board, state = module.from_chess(source)
    original = board.copy(), state.copy()
    history = np.zeros(256, dtype=np.uint64)
    length = module._seed_history(source, history)
    prefix = history[:length].copy()
    keys = np.zeros(module.TT_LIMIT, dtype=np.uint64)
    moves = np.full(module.TT_LIMIT, -1, dtype=np.int64)
    candidate = hasattr(module, "new_score_table")
    score_data, score_context = module.new_score_table() if candidate else (None, None)
    total = np.zeros(16, dtype=np.int64)
    best, completed = -1, 0
    rows = []
    cutoff = started + 60 if deadline is None else deadline
    for current in range(1, depth + 1):
        counts = np.zeros(module.COUNTER_SIZE if candidate else 4, dtype=np.int64)
        args: tuple[Any, ...] = (
            board, state, current, cutoff, counts, best, history, length, keys, moves
        )
        if candidate:
            args += (score_data, score_context, use_tt, use_lmr)
        tick = time.monotonic()
        found, score = module.compiled_root_search(*args)
        elapsed = time.monotonic() - tick
        assert np.array_equal(board, original[0]) and np.array_equal(state, original[1])
        assert np.array_equal(history[:length], prefix)
        total[: len(counts)] += counts
        row = {
            "depth": current,
            "move": module.move_to_uci(int(found)),
            "score": int(score),
            "nodes": int(counts[0]),
            "elapsed_s": elapsed,
            "complete": not bool(counts[1]),
            "counters": counts.tolist(),
        }
        rows.append(row)
        if counts[1]:
            break
        best, completed = found, current
    return {
        "iterations": rows,
        "elapsed_s": time.monotonic() - started,
        "requested_depth": depth,
        "completed_depth": completed,
        "complete": completed == depth,
        "nodes": int(total[0]),
        "restored": True,
        "counters": total.tolist(),
        "stats": {name: int(total[index]) for index, name in enumerate(COUNTERS)},
    }


def summarize(directory: Path) -> dict[str, Any]:
    stage = json.loads((directory / "stage.json").read_text())
    rows = [json.loads(line) for line in (directory / "runs.jsonl").read_text().splitlines()]
    per_position = []
    mismatches = []
    for name in stage["position_ids"]:
        measured = [r for r in rows if r["id"] == name and r["complete"]]
        if any(
            sum(r["label"] == label for r in measured) != stage["parameters"]["repeats"]
            for label in CONFIGS
        ):
            continue
        medians = {
            label: statistics.median(r["elapsed_s"] for r in measured if r["label"] == label)
            for label in CONFIGS
        }
        reference = next(r for r in measured if r["label"] == "v7")
        baseline_scores = [r["score"] for r in reference["iterations"]]
        for row in measured:
            if row["label"] == "tt" and [r["score"] for r in row["iterations"]] != baseline_scores:
                mismatches.append(
                    {
                        "id": name,
                        "repeat": row["repeat"],
                        "v7_scores": baseline_scores,
                        "tt_scores": [r["score"] for r in row["iterations"]],
                    }
                )
        per_position.append(
            {
                "id": name,
                "median_elapsed_s": medians,
                "latency_ratios": {label: medians[label] / medians["v7"] for label in CONFIGS},
                "v7_relative_mad": statistics.median(
                    abs(r["elapsed_s"] - medians["v7"]) for r in measured if r["label"] == "v7"
                )
                / medians["v7"],
                "scores": {
                    label: [
                        r["score"]
                        for r in next(row for row in measured if row["label"] == label)[
                            "iterations"
                        ]
                    ]
                    for label in CONFIGS
                },
                "moves": {
                    label: [
                        r["move"]
                        for r in next(row for row in measured if row["label"] == label)[
                            "iterations"
                        ]
                    ]
                    for label in CONFIGS
                },
                "median_nodes": {
                    label: statistics.median(r["nodes"] for r in measured if r["label"] == label)
                    for label in CONFIGS
                },
            }
        )
    variants = {}
    for label in CONFIGS:
        subset = [r for r in rows if r["label"] == label]
        variants[label] = {
            "rows": len(subset),
            "complete_rows": sum(r["complete"] for r in subset),
            "total_stats": {key: sum(r["stats"][key] for r in subset) for key in COUNTERS},
            "gmean_latency_ratio": math.exp(
                statistics.mean(math.log(p["latency_ratios"][label]) for p in per_position)
            )
            if per_position
            else None,
            "worst_position_median_ratio": max(
                (p["latency_ratios"][label] for p in per_position), default=None
            ),
        }
    result = {
        "stage_status": stage["status"],
        "rows": len(rows),
        "expected_rows": stage["expected_rows"],
        "source_modules": stage["modules"],
        "complete": stage["status"] == "completed" and all(r["complete"] for r in rows),
        "positions": per_position,
        "variants": variants,
        "tt_full_window_score_mismatches": mismatches,
        "tt_full_window_scores_match": not mismatches
        and len(per_position) == len(stage["position_ids"]),
        "scope": "Previously seen regressions; LMR scores/nodes may differ. Fixed-depth "
        "speed alone does not establish same-clock move quality or strength.",
        "cost_scope": "Allocations, seeding and complete iterative D1..D search are timed; "
        "imports and per-case warmup are separately recorded.",
    }
    checkpoint(directory / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit-s", type=int, default=600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    assert 1 <= args.depth < 64 and args.repeats > 0 and 0 < args.limit_s <= 1200
    parameters = {"depth": args.depth, "repeats": args.repeats, "limit_s": args.limit_s}
    files = {"v7": "baselines.online_v7.agent", "candidate": "prototypes.search_core.agent"}
    modules: dict[str, Any] = {}
    metadata: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "environment": environment(),
        "parameters": parameters,
        "modules": {},
        "scope": "14 previously seen ordinary/Slav positions; not independent validation",
        "order": (
            "All four configurations warm per position, then rotating order by position/repeat"
        ),
        "completed_rows": 0,
        "elapsed_s": 0.0,
    }
    args.out.mkdir(parents=True, exist_ok=args.resume)
    stage_path, run_path = args.out / "stage.json", args.out / "runs.jsonl"
    done: set[tuple[str, int, str]] = set()
    elapsed_before = 0.0
    if args.resume:
        metadata = json.loads(stage_path.read_text())
        assert metadata["status"] == "incomplete" and metadata["parameters"] == parameters
        elapsed_before = metadata["elapsed_s"]
        for line in run_path.read_text().splitlines() if run_path.exists() else []:
            row = json.loads(line)
            key = row["id"], row["repeat"], row["label"]
            assert key not in done
            done.add(key)
        metadata["completed_rows"] = len(done)
        metadata["status"] = "running"
        metadata.setdefault("resumed_utc", []).append(datetime.now(UTC).isoformat())
    assert elapsed_before < args.limit_s
    started = time.monotonic()
    signal.signal(signal.SIGALRM, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.alarm(max(1, int(args.limit_s - elapsed_before)))
    checkpoint(stage_path, metadata)
    try:
        for label, name in files.items():
            tick = time.monotonic()
            module = importlib.import_module(name)
            assert module.__file__ is not None
            digest = sha256(Path(module.__file__))
            if label == "v7":
                assert digest == V7_SHA256
            if args.resume:
                assert metadata["modules"][label]["sha256"] == digest
            modules[label] = module
            metadata["modules"][label] = {
                "name": name,
                "file": str(Path(module.__file__).resolve()),
                "sha256": digest,
                "import_including_compile_s": time.monotonic() - tick,
                "search_warmup_s": module.SEARCH_WARMUP_SECONDS,
                "root_signatures": [str(s) for s in module.compiled_root_search.signatures],
            }
        boards = sources()
        metadata["position_ids"] = [name for name, _ in boards]
        metadata["expected_rows"] = len(boards) * len(CONFIGS) * args.repeats
        metadata["warmups"] = []
        checkpoint(stage_path, metadata)
        with run_path.open("a" if args.resume else "x") as output:
            for index, (name, board) in enumerate(boards):
                if all(
                    (name, repeat, label) in done
                    for repeat in range(args.repeats)
                    for label in CONFIGS
                ):
                    continue
                for label, (tt, lmr) in CONFIGS.items():
                    module = modules["v7" if label == "v7" else "candidate"]
                    tick = time.monotonic()
                    warm = fixed_search(module, board, args.depth, tt, lmr)
                    metadata["warmups"].append(
                        {
                            "id": name,
                            "label": label,
                            "elapsed_s": time.monotonic() - tick,
                            "complete": warm["complete"],
                        }
                    )
                    checkpoint(stage_path, metadata)
                for repeat in range(args.repeats):
                    labels = list(CONFIGS)
                    offset = (index + repeat) % len(labels)
                    labels = labels[offset:] + labels[:offset]
                    for label in labels:
                        key = name, repeat, label
                        if key in done:
                            continue
                        source_label = "v7" if label == "v7" else "candidate"
                        module = modules[source_label]
                        assert (
                            sha256(Path(module.__file__))
                            == metadata["modules"][source_label]["sha256"]
                        )
                        tt, lmr = CONFIGS[label]
                        row = {
                            "id": name,
                            "repeat": repeat,
                            "label": label,
                            "use_tt": tt,
                            "use_lmr": lmr,
                            **fixed_search(module, board, args.depth, tt, lmr),
                        }
                        output.write(json.dumps(row) + "\n")
                        output.flush()
                        done.add(key)
                        metadata["completed_rows"] = len(done)
                        checkpoint(stage_path, metadata)
                print(name, metadata["completed_rows"], flush=True)
        assert metadata["completed_rows"] == metadata["expected_rows"]
        metadata.update(status="completed", exit_code=0)
    except BaseException as error:
        metadata.update(status="incomplete", error=f"{type(error).__name__}: {error}", exit_code=1)
        raise
    finally:
        signal.alarm(0)
        metadata["elapsed_s"] = elapsed_before + time.monotonic() - started
        metadata["finished_utc"] = datetime.now(UTC).isoformat()
        checkpoint(stage_path, metadata)
    result = summarize(args.out)
    assert result["complete"], "Incomplete fixed-depth measurement"
    assert result["tt_full_window_scores_match"], "TT-only full-window score mismatch"
    print(json.dumps({k: v for k, v in result.items() if k != "positions"}, indent=2))


if __name__ == "__main__":
    main()

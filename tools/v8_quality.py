"""Bounded four-way real-entry comparison; private positions and teacher labels stay local.

Reuse tools.search_decisions.probe for history, legality, completed iterations and
unmake checks. Public summaries expose anonymous position IDs and aggregates only.
Teacher labels are offline evidence, never imported by any submission module.
"""

import argparse
import importlib
import json
import signal
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess

from tools.online_review import sha256
from tools.release_environment import environment
from tools.search_decisions import probe

STOP_REQUESTED = False
V7_HASH = "aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d"
OPTIONS = {"off": (False, False), "tt": (True, False), "lmr": (False, True),
           "both": (True, True)}


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def position(row: dict[str, Any]) -> chess.Board:
    board = chess.Board(row["start_fen"])
    for move in row["history"]:
        board.push_uci(move)
    assert board.fen() == row["position"]["fen"], row["key"]
    return board


def configure(module: Any, label: str) -> None:
    if label != "v7":
        tt, lmr = OPTIONS[label]
        module.set_search_options(tt=tt, lmr=lmr)
        assert module.USE_SCORE_TT is tt and module.USE_LMR is lmr


def stop(_signal: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise TimeoutError("Predeclared quality-stage wall limit")


def run(args: argparse.Namespace) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = False
    if args.split == "holdout":
        if not args.freeze:
            raise ValueError("Holdout requires a previously saved configuration freeze")
        freeze = json.loads(args.freeze.read_text())
        assert freeze["candidate_sha256"] == args.sha256
        assert freeze["configuration"] in args.configurations
        assert args.configurations == ["v7", freeze["configuration"]]
        assert freeze["holdout_positions_sha256"] == sha256(args.positions)
    rows = jsonl(args.positions)
    if args.select:
        wanted = set(args.select)
        rows = [r for r in rows if r["key"] in wanted]
        assert len(rows) == len(wanted)
    assert len({r["key"] for r in rows}) == len(rows)
    immutable = {
        "candidate_sha256": args.sha256, "baseline_sha256": V7_HASH,
        "positions_sha256": sha256(args.positions), "selection": [r["key"] for r in rows],
        "configurations": args.configurations, "repeats": args.repeats,
        "split": args.split, "candidate_module": args.candidate,
        "freeze_sha256": sha256(args.freeze) if args.freeze else None,
    }
    args.out.mkdir(parents=True, exist_ok=args.resume)
    stage_path, result_path = args.out / "stage.json", args.out / "runs.jsonl"
    previous = json.loads(stage_path.read_text()) if args.resume and stage_path.exists() else None
    if previous:
        assert previous["immutable"] == immutable, "Resume requires identical inputs and sources"
    completed = jsonl(result_path) if result_path.exists() else []
    done = {(r["key"], r["configuration"], r["repeat"]) for r in completed}
    assert len(done) == len(completed), "Duplicate result rows are not a valid checkpoint"
    started = time.monotonic()
    stage: dict[str, Any] = {
        "immutable": immutable, "status": "running", "expected_rows": (
            len(rows) * len(args.configurations) * args.repeats),
        "completed_rows": len(completed), "started_utc": datetime.now(UTC).isoformat(),
        "environment": environment(), "limit_s": args.limit_s,
        "order": "Rotate then reverse configuration order across positions and repeats",
        "clock_policy": "Original recorded remaining clocks; unchanged entry time allocation",
        "previous_attempts": ([*previous.get("previous_attempts", []), {
            k: previous.get(k) for k in ("status", "started_utc", "ended_utc", "elapsed_s")
        }]) if previous else [],
        "modules": {},
    }
    write_json(stage_path, stage)
    signal.signal(signal.SIGALRM, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.alarm(args.limit_s)
    try:
        modules: dict[str, Any] = {}
        for name, digest in (("baselines.online_v7.agent", V7_HASH), (args.candidate, args.sha256)):
            tick = time.monotonic()
            module = importlib.import_module(name)
            elapsed = time.monotonic() - tick
            assert module.__file__ is not None
            actual = Path(module.__file__).resolve()
            assert sha256(actual) == digest, (actual, digest)
            implementation = Path(
                module.compiled_root_search.py_func.__code__.co_filename).resolve()
            assert implementation == actual, "Actual compiled root must belong to this source"
            modules[name] = module
            stage["modules"][name] = {
                "file": str(actual), "sha256": digest, "import_including_compile_s": elapsed,
                "compiled_search_warmup_s": getattr(module, "SEARCH_WARMUP_SECONDS", None),
                "compiled_root_implementation": str(implementation),
            }
        for label in args.configurations:
            module = modules["baselines.online_v7.agent" if label == "v7" else args.candidate]
            configure(module, label)
            tick = time.monotonic()
            module.timed_search(chess.Board(), 0.05)
            stage.setdefault("warmup_s", {})[label] = time.monotonic() - tick
        write_json(stage_path, stage)
        with result_path.open("a") as output:
            for i, row in enumerate(rows):
                board = position(row)
                clock = round(row["position"]["clock_before_s"] * 1000)
                for repetition in range(args.repeats):
                    offset = (i + repetition) % len(args.configurations)
                    order = args.configurations[offset:] + args.configurations[:offset]
                    if (i + repetition) % 2:
                        order = list(reversed(order))
                    for label in order:
                        identity = row["key"], label, repetition + 1
                        if identity in done:
                            continue
                        module = modules[
                            "baselines.online_v7.agent" if label == "v7" else args.candidate]
                        configure(module, label)
                        measured = probe(module, board, clock)
                        record = {
                            "key": row["key"], "id": f"P{i + 1:02}", "configuration": label,
                            "repeat": repetition + 1, **measured,
                            "nodes": sum(r["nodes"] for r in measured["iterations"]),
                            "search_stats": dict(getattr(module, "LAST_SEARCH_STATS", {})),
                        }
                        output.write(json.dumps(record) + "\n")
                        output.flush()
                        done.add(identity)
                        stage["completed_rows"] = len(done)
                        stage["elapsed_s"] = time.monotonic() - started
                        write_json(stage_path, stage)
                        print(record["id"], label, repetition + 1, record["depth"],
                              round(record["elapsed_s"], 3), record["nodes"], flush=True)
        stage["status"] = "completed"
    except BaseException as exc:
        stage["status"] = ("interrupted" if STOP_REQUESTED
                           or isinstance(exc, (TimeoutError, KeyboardInterrupt)) else "failed")
        stage["error"] = repr(exc)
        raise
    finally:
        signal.alarm(0)
        stage["ended_utc"] = datetime.now(UTC).isoformat()
        stage["elapsed_s"] = time.monotonic() - started
        write_json(stage_path, stage)


def labels(
    paths: list[Path], positions_path: Path, source_paths: list[Path], minimum_nodes: int
) -> dict[str, dict[str, Any]]:
    """Reject labels whose recorded source cannot be matched to this exact history."""
    target_positions = {r["key"]: r for r in jsonl(positions_path)}
    sources = {sha256(p): {r["key"]: r for r in jsonl(p)}
               for p in [positions_path, *source_paths]}
    merged: dict[str, dict[str, Any]] = {}
    teacher_hashes = set()
    for path in paths:
        metadata = json.loads(path.with_suffix(".meta.json").read_text())
        teacher_hashes.add(metadata["binary_sha256"])
        assert metadata["nodes_per_forced_move"] >= minimum_nodes
        original = sources[metadata["position_input_sha256"]]
        for row in jsonl(path):
            if row["key"] not in target_positions:
                continue
            old, current = original[row["key"]], target_positions[row["key"]]
            for field in ("start_fen", "history"):
                assert old[field] == current[field], (row["key"], field)
            assert old["position"]["fen"] == current["position"]["fen"]
            target = merged.setdefault(row["key"], {"moves": {}, "root": row["root"]})
            target["root"] = row["root"]
            target["moves"].update(row["moves"])
    assert len(teacher_hashes) == 1, "Do not silently mix teacher binaries"
    return merged


def quality(reference: dict[str, Any], move: str) -> dict[str, Any]:
    root = reference["root"][0]
    answer = reference["moves"].get(move)
    if answer is None:
        return {"missing": True}
    uncertain = any(p.get(bound, False) for p in (root, answer)
                    for bound in ("lowerbound", "upperbound"))
    regret = (max(0, root["cp"] - answer["cp"])
              if root["cp"] is not None and answer["cp"] is not None else None)
    return {"missing": False, "regret_cp": regret, "bound_uncertain": uncertain,
            "mate_transition": [root["mate"], answer["mate"]]}


def summarize(args: argparse.Namespace) -> None:
    stage = json.loads((args.runs / "stage.json").read_text())
    rows = jsonl(args.runs / "runs.jsonl")
    assert sha256(args.positions) == stage["immutable"]["positions_sha256"]
    teacher = labels(args.labels, args.positions, args.label_sources, args.minimum_label_nodes)
    configurations = stage["immutable"]["configurations"]
    profiles: dict[str, Any] = {}
    missing: list[dict[str, str]] = []
    by_position: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        result = quality(teacher[row["key"]], row["move"]) if row["key"] in teacher else {
            "missing": True}
        row["quality"] = result
        if result["missing"]:
            missing.append({"key": row["key"], "move": row["move"]})
        by_position.setdefault(row["id"], {}).setdefault(row["configuration"], []).append(row)
    for label in configurations:
        measured = [r for r in rows if r["configuration"] == label]
        known = [r["quality"] for r in measured if not r["quality"]["missing"]]
        cp = [q["regret_cp"] for q in known if q["regret_cp"] is not None
              and not q["bound_uncertain"]]
        profiles[label] = {
            "calls": len(measured), "labeled_calls": len(known), "ordinary_cp_calls": len(cp),
            "mean_regret_cp": statistics.mean(cp) if cp else None,
            "errors_ge100_cp": sum(v >= 100 for v in cp),
            "positions_any_ge100_cp": sum(any(
                not r["quality"]["missing"] and r["quality"]["regret_cp"] is not None
                and r["quality"]["regret_cp"] >= 100 for r in group.get(label, []))
                for group in by_position.values()),
            "positions_repeated_move_varies": sum(
                len({r["move"] for r in group.get(label, [])}) > 1
                for group in by_position.values()),
            "mate_transitions": [q["mate_transition"] for q in known
                                 if any(v is not None for v in q["mate_transition"])],
            "mean_elapsed_s": (statistics.mean(r["elapsed_s"] for r in measured)
                               if measured else None),
            "mean_nodes": statistics.mean(r["nodes"] for r in measured) if measured else None,
            "mean_completed_depth": (statistics.mean(r["depth"] for r in measured)
                                     if measured else None),
            "all_legal_clock_history_unmake": all(r["within_clock"] and r["history_verified"]
                and r["unmake_verified"] for r in measured),
            "search_counters_sum": {
                key: sum(r["search_stats"].get(key, 0) for r in measured)
                for key in sorted({k for r in measured for k, value in r["search_stats"].items()
                                   if isinstance(value, (int, float))})},
        }
    contrasts: dict[str, Any] = {}
    for label in configurations:
        if label == "v7":
            continue
        pairs = [(groups["v7"], groups[label]) for groups in by_position.values()
                 if "v7" in groups and label in groups]
        depth = [statistics.mean(r["depth"] for r in new)
                 - statistics.mean(r["depth"] for r in old) for old, new in pairs]
        matched_cp = []
        anonymous_deltas = []
        for old, new in pairs:
            if all(not r["quality"]["missing"] and r["quality"]["regret_cp"] is not None
                   and not r["quality"]["bound_uncertain"] for r in old + new):
                old_cp = statistics.mean(r["quality"]["regret_cp"] for r in old)
                new_cp = statistics.mean(r["quality"]["regret_cp"] for r in new)
                matched_cp.append(new_cp - old_cp)
                anonymous_deltas.append({"id": old[0]["id"], "v7_regret_cp": old_cp,
                                         "candidate_regret_cp": new_cp,
                                         "change_cp": new_cp - old_cp})
        contrasts[label] = {
            "positions_paired": len(pairs), "completed_depth_higher_equal_lower": [
                sum(d > 0 for d in depth), sum(d == 0 for d in depth), sum(d < 0 for d in depth)],
            "teacher_cp_positions_paired": len(matched_cp),
            "mean_regret_change_cp": statistics.mean(matched_cp) if matched_cp else None,
            "better_equivalent_worse_at_50cp": [sum(d < -50 for d in matched_cp),
                sum(abs(d) <= 50 for d in matched_cp), sum(d > 50 for d in matched_cp)],
            "worst_regret_increase_cp": max(matched_cp) if matched_cp else None,
            "positions_worse_ge100_cp": sum(d >= 100 for d in matched_cp),
            "positions_better_ge100_cp": sum(d <= -100 for d in matched_cp),
            "new_ge100_error_positions": sum(p["v7_regret_cp"] < 100
                and p["candidate_regret_cp"] >= 100 for p in anonymous_deltas),
            "resolved_ge100_error_positions": sum(p["v7_regret_cp"] >= 100
                and p["candidate_regret_cp"] < 100 for p in anonymous_deltas),
            "anonymous_position_deltas": anonymous_deltas,
        }
    summary = {
        "status": stage["status"], "rows": len(rows), "expected_rows": stage["expected_rows"],
        "candidate_sha256": stage["immutable"]["candidate_sha256"],
        "position_source_sha256": stage["immutable"]["positions_sha256"],
        "split": stage["immutable"]["split"], "profiles": profiles, "contrasts_vs_v7": contrasts,
        "missing_unique_position_moves": len({(r["key"], r["move"]) for r in missing}),
        "labels_sha256": [sha256(p) for p in args.labels],
        "minimum_teacher_nodes": args.minimum_label_nodes,
        "label_history_source_hash_verified": True,
        "limitations": ["Selective depth and NPS do not establish strength",
                         "Teacher cp and mate are separate; a first-move mismatch is not an error",
                         "Means with missing labels are incomplete; use matched-position contrasts",
                         "All online positions and old Slav losses are development regressions"],
    }
    write_json(args.out, summary)
    # Keep this selection private: the old tools.teacher_moves accepts key/move JSONL.
    if args.missing:
        unique = sorted({(r["key"], r["move"]) for r in missing})
        args.missing.write_text("".join(
            json.dumps({"key": k, "move": m}) + "\n" for k, m in unique))
    print(json.dumps(summary, indent=2))


def endgames(args: argparse.Namespace) -> None:
    """Reuse v5_suite WDL scoring on the predeclared first eight fixtures per source."""
    freeze = json.loads(args.freeze.read_text())
    selected = freeze["configuration"]
    assert selected in OPTIONS and len(args.fixtures) == 2
    assert [sha256(p) for p in args.fixtures] == freeze["endgame_fixture_sha256"]
    if args.out.exists():
        raise RuntimeError("Refusing to replace a final-validation result")
    report: dict[str, Any] = {
        "status": "running", "started_utc": datetime.now(UTC).isoformat(),
        "candidate_sha256": freeze["candidate_sha256"], "configuration": selected,
        "fixture_sha256": freeze["endgame_fixture_sha256"], "budget_s": 0.25, "repeats": 2,
        "expected_rows": 64, "completed_rows": 0,
        "scope": "First eight fixtures from each of two prior v5 validation sources; "
                 "not used for v8 tuning, but previously seen across versions",
        "environment": environment(), "runs": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, report)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(180)
    try:
        modules = {"v7": importlib.import_module("baselines.online_v7.agent"),
                   selected: importlib.import_module("prototypes.search_core.agent")}
        for label, module in modules.items():
            assert module.__file__ is not None
            assert sha256(Path(module.__file__)) == (
                V7_HASH if label == "v7" else freeze["candidate_sha256"])
            configure(module, label)
            module.timed_search(chess.Board(), 0.05)
        wdl = {"loss": -1, "blessed-loss": 0, "draw": 0, "cursed-win": 0, "win": 1}
        for group_index, fixture_path in enumerate(args.fixtures):
            fixtures = json.loads(fixture_path.read_text())[:8]
            assert len(fixtures) == 8
            for index, fixture in enumerate(fixtures):
                board = chess.Board(fixture["fen"])
                for move in fixture["history"]:
                    board.push_uci(move)
                original = board.fen(), list(board.move_stack)
                choices = {r["uci"]: r for r in fixture["label"]["moves"]}
                root_wdl = wdl[fixture["label"]["category"]]
                assert max(-wdl[r["category"]] for r in choices.values()) == root_wdl
                for repeat in range(2):
                    order = ["v7", selected] if (index + repeat) % 2 == 0 else [selected, "v7"]
                    for label in order:
                        configure(modules[label], label)
                        tick = time.monotonic()
                        move, depth, nodes = modules[label].timed_search(board, 0.25)
                        elapsed = time.monotonic() - tick
                        assert (board.fen(), list(board.move_stack)) == original
                        assert chess.Move.from_uci(move) in board.legal_moves
                        chosen_wdl = -wdl[choices[move]["category"]]
                        report["runs"].append({
                            "id": f"E{group_index * 8 + index + 1:02}", "configuration": label,
                            "repeat": repeat + 1, "move": move, "depth": depth, "nodes": nodes,
                            "elapsed_s": elapsed, "root_wdl": root_wdl, "chosen_wdl": chosen_wdl,
                            "wdl_regret": root_wdl - chosen_wdl,
                            "preserved_wdl": root_wdl == chosen_wdl,
                        })
                        report["completed_rows"] += 1
                        write_json(args.out, report)
        report["status"] = "completed"
    except BaseException as exc:
        report["status"], report["error"] = "failed", repr(exc)
        raise
    finally:
        signal.alarm(0)
        report["ended_utc"] = datetime.now(UTC).isoformat()
        report["elapsed_s"] = time.monotonic() - started
        write_json(args.out, report)
    summary = {k: value for k, value in report.items() if k != "runs"}
    summary["profiles"] = {}
    for label in ("v7", selected):
        measured = [r for r in report["runs"] if r["configuration"] == label]
        summary["profiles"][label] = {
            "calls": len(measured), "preserved_wdl": sum(r["preserved_wdl"] for r in measured),
            "total_wdl_regret": sum(r["wdl_regret"] for r in measured),
            "mean_elapsed_s": statistics.mean(r["elapsed_s"] for r in measured),
            "max_budget_overrun_s": max(r["elapsed_s"] - 0.25 for r in measured),
            "mean_depth": statistics.mean(r["depth"] for r in measured),
        }
    write_json(args.summary, summary)
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure")
    measure.add_argument("--positions", type=Path, required=True)
    measure.add_argument("--candidate", default="prototypes.search_core.agent")
    measure.add_argument("--sha256", required=True)
    measure.add_argument("--configurations", nargs="+", choices=["v7", *OPTIONS],
                         default=["v7", "tt", "lmr", "both"])
    measure.add_argument("--repeats", type=int, default=2)
    measure.add_argument("--select", nargs="*")
    measure.add_argument("--split", choices=["development", "holdout"], default="development")
    measure.add_argument("--freeze", type=Path)
    measure.add_argument("--limit-s", type=int, default=900)
    measure.add_argument("--resume", action="store_true")
    measure.add_argument("--out", type=Path, required=True)
    score = commands.add_parser("summarize")
    score.add_argument("--runs", type=Path, required=True)
    score.add_argument("--labels", nargs="+", type=Path, required=True)
    score.add_argument("--positions", type=Path, required=True)
    score.add_argument("--label-sources", nargs="*", type=Path, default=[])
    score.add_argument("--minimum-label-nodes", type=int, default=4_000_000)
    score.add_argument("--missing", type=Path)
    score.add_argument("--out", type=Path, required=True)
    endgame = commands.add_parser("endgames")
    endgame.add_argument("--fixtures", nargs=2, type=Path, required=True)
    endgame.add_argument("--freeze", type=Path, required=True)
    endgame.add_argument("--out", type=Path, required=True)
    endgame.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "measure":
        if args.repeats < 1 or len(set(args.configurations)) != len(args.configurations):
            raise ValueError("Positive repeats and distinct configurations required")
        run(args)
    elif args.command == "summarize":
        summarize(args)
    else:
        endgames(args)


if __name__ == "__main__":
    main()

"""Package the frozen v4 and test it independently; no private online data required."""

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import chess
import chess.pgn

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.rules import INIT_BUDGET_S, MAX_UNZIPPED_BYTES
from harness.sandbox import local

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SHA256 = "7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4"
BASELINE_SHA256 = "b08ab63e695f971e6322353eb5bba4657c91e901ac9b0b6fb9a326f1def56297"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(archive: Path, directory: Path) -> None:
    source = ROOT / "prototypes/numba_kernel/agent.py"
    if digest(source) != CANDIDATE_SHA256:
        raise RuntimeError("Frozen v4 source hash mismatch; refusing to package another agent")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, path in (("agent.py", source), ("LICENSE", ROOT / "LICENSE")):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive) as packed:
        if packed.namelist() != ["agent.py", "LICENSE"] or packed.testzip() is not None:
            raise RuntimeError("Unexpected archive contents")
        if sum(item.file_size for item in packed.infolist()) > MAX_UNZIPPED_BYTES:
            raise RuntimeError("Archive exceeds the local harness size limit")
        packed.extractall(directory)
    if (directory / "agent.py").read_bytes() != source.read_bytes():
        raise RuntimeError("Extracted candidate is not byte-identical")


def environment() -> dict[str, object]:
    packages = {}
    for name in ("chess", "numpy", "numba", "llvmlite", "torch", "onnxruntime", "ruff", "mypy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    details: dict[str, object] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "uv_lock_sha256": digest(ROOT / "uv.lock"),
        "address_space_limit": resource.getrlimit(resource.RLIMIT_AS),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "image_os": os.environ.get("ImageOS"),  # noqa: SIM112 - GitHub runner's actual key
        "image_version": os.environ.get("ImageVersion"),  # noqa: SIM112 - GitHub's actual key
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "thread_limits": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMBA_NUM_THREADS",
                "MKL_NUM_THREADS",
            )
        },
        "scope": "Host compatibility only; not the official competition container",
        "limitations": [
            "No 2 GB memory quota or read-only filesystem imposed",
            "Network isolation and opponent process suspension are not reproduced",
            "Unmodified local referee: 60 s init, 300-ply material adjudication, claim_draw=True",
            "Two short smoke games do not measure playing strength",
        ],
    }
    if sys.platform == "linux":
        details["cpu_affinity"] = sorted(os.sched_getaffinity(0))
        for label, path in (
            ("meminfo", "/proc/meminfo"),
            ("cpuinfo", "/proc/cpuinfo"),
            ("cgroup_memory_max", "/sys/fs/cgroup/memory.max"),
            ("cgroup_cpu_max", "/sys/fs/cgroup/cpu.max"),
        ):
            if Path(path).is_file():
                details[label] = Path(path).read_text()
    return details


def check_runner(directory: Path) -> dict[str, object]:
    player = local(directory)
    checks = []
    try:
        started = time.monotonic()
        player.start(INIT_BUDGET_S)
        initialization = time.monotonic() - started
        for fen, remaining in (
            (chess.STARTING_FEN, 5000),
            ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", 1000),
            (chess.STARTING_FEN, 1),
        ):
            started = time.monotonic()
            uci = player.move(fen, remaining)
            elapsed = (time.monotonic() - started) * 1000
            if chess.Move.from_uci(uci) not in chess.Board(fen).legal_moves:
                raise RuntimeError(f"Illegal runner move: {uci}")
            if elapsed >= remaining:
                raise RuntimeError(f"Runner round trip {elapsed} ms exceeded {remaining} ms")
            checks.append(
                {"fen": fen, "remaining_ms": remaining, "move": uci, "round_trip_ms": elapsed}
            )
    finally:
        player.stop()
    return {"init_seconds": initialization, "checks": checks, "stderr": player.stderr_tail}


def check_games(directory: Path, output: Path) -> list[dict[str, object]]:
    # Reuse an already public and already tested opening; this is not a new holdout.
    opening = json.loads((ROOT / "benchmarks/astra-v4/validation-openings.json").read_text())[0]
    baseline = ROOT / "baselines/online_v3"
    if digest(baseline / "agent.py") != BASELINE_SHA256:
        raise RuntimeError("Frozen online v3 hash mismatch")
    games: list[dict[str, object]] = []
    for index in range(2):
        white_dir, black_dir = (directory, baseline) if index == 0 else (baseline, directory)
        white, black = local(white_dir), local(black_dir)
        started = time.monotonic()
        result = play_match(white, black, 10_000, 100, start_fen=opening["fen"])
        record = {
            "game": index + 1,
            "candidate_color": "white" if index == 0 else "black",
            "candidate_sha256": CANDIDATE_SHA256,
            "opponent_sha256": BASELINE_SHA256,
            "opening": opening,
            "base_ms": 10_000,
            "increment_ms": 100,
            "result": result.result,
            "termination": result.termination,
            "elapsed_seconds": time.monotonic() - started,
            "white_stderr": white.stderr_tail,
            "black_stderr": black.stderr_tail,
        }
        games.append(record)
        (output / f"game-{index + 1}.pgn").write_text(result.pgn + "\n")
        (output / "games.json").write_text(json.dumps(games, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if result.termination in FAILED_TERMINATIONS or result.result == "void":
            raise RuntimeError(f"Smoke game failed: {result.termination}")
        replay = chess.pgn.read_game(io.StringIO(result.pgn))
        if replay is None or replay.errors:
            raise RuntimeError("Cannot replay smoke PGN")
        board = replay.board()
        for move in replay.mainline_moves():
            if move not in board.legal_moves:
                raise RuntimeError("Illegal move in smoke PGN")
            board.push(move)
        finish = board.outcome(claim_draw=True)
        if finish is None or finish.result() != replay.headers["Result"]:
            raise RuntimeError("Smoke game must reach a natural result, without adjudication")
    return games


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/v4-ci"))
    parser.add_argument("--require-linux", action="store_true")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Run this release check with Python 3.12")
    if args.require_linux and (sys.platform != "linux" or platform.machine() != "x86_64"):
        raise RuntimeError("CI requires Linux x86_64")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"environment": environment(), "status": "running"}
    try:
        with tempfile.TemporaryDirectory(prefix="nullgambit-v4-") as temporary:
            directory = Path(temporary)
            archive = output / "astra-v4.zip"
            package(archive, directory)
            report.update(
                {
                    "candidate_sha256": digest(directory / "agent.py"),
                    "archive_sha256": digest(archive),
                }
            )
            report["runner"] = check_runner(directory)
            probe = subprocess.run(
                [sys.executable, "-I", str(ROOT / "tools/v4_search_probe.py"), str(directory)],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=INIT_BUDGET_S + 10,
                check=False,
            )
            (output / "search-probe.log").write_text(probe.stdout + probe.stderr)
            probe.check_returncode()
            search = json.loads(probe.stdout)
            if search["agent_sha256"] != CANDIDATE_SHA256:
                raise RuntimeError("Search probe imported the wrong source")
            report["isolated_search"] = search
            report["games"] = check_games(directory, output)
            if digest(directory / "agent.py") != CANDIDATE_SHA256:
                raise RuntimeError("Extracted source changed during testing")
        report["status"] = "passed"
    except Exception as error:
        report.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        report["children_maxrss"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        report["maxrss_unit"] = "bytes" if sys.platform == "darwin" else "KiB"
        (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Frozen v4 package, real search, runner and two smoke games passed: {output}")


if __name__ == "__main__":
    main()

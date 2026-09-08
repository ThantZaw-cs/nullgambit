"""Check the single-file ZIP through a fresh platform-runner process."""

import argparse
import hashlib
import json
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import chess

from harness.rules import INIT_BUDGET_S
from harness.sandbox import local


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("submission.zip"))
    parser.add_argument("--source", type=Path, default=Path("agent.py"))
    parser.add_argument("--out", type=Path, default=Path("benchmarks/positional-runtime.json"))
    args = parser.parse_args()
    root = Path(".venv").resolve()
    directory = root / f"submission-check-{uuid.uuid4().hex}"
    if not directory.resolve().is_relative_to(Path.cwd().resolve()):
        raise SystemExit("The package test directory must stay inside the workspace")
    # Use inherited directory permissions; Windows' special mode=0700 handling
    # in tempfile can make its directories inaccessible to a sandboxed process.
    directory.mkdir()
    player = local(directory)
    try:
        source = args.source.read_bytes()
        with zipfile.ZipFile(args.archive) as archive:
            names = archive.namelist()
            if (
                "agent.py" not in names
                or len(set(names)) != len(names)
                or set(names) - {"agent.py", "LICENSE"}
                or archive.testzip() is not None
            ):
                raise SystemExit("Expected an intact root agent.py and optional LICENSE")
            if archive.read("agent.py") != source:
                raise SystemExit("The ZIP is stale; rebuild it before checking")
            archive.extractall(directory)
        started = time.monotonic()
        player.start(INIT_BUDGET_S)
        initialization = time.monotonic() - started
        checks: list[dict[str, object]] = []
        for fen, remaining in (
            (chess.STARTING_FEN, 5000),
            ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", 1000),
            (chess.STARTING_FEN, 1),
        ):
            started = time.monotonic()
            move = player.move(fen, remaining)
            elapsed_ms = (time.monotonic() - started) * 1000
            if chess.Move.from_uci(move) not in chess.Board(fen).legal_moves:
                raise SystemExit(f"Illegal packaged move: {move}")
            checks.append({"remaining_ms": remaining, "move": move, "round_trip_ms": elapsed_ms})
    finally:
        player.stop()
        if directory.resolve().is_relative_to(root) and root.is_relative_to(Path.cwd().resolve()):
            shutil.rmtree(directory)
        else:
            raise RuntimeError("Refusing to clean up a test directory outside the workspace")
    report = {
        "source": str(args.source),
        "archive": str(args.archive),
        "agent_sha256": hashlib.sha256(source).hexdigest(),
        "init_seconds": initialization,
        "checks": checks,
        "stderr": player.stderr_tail,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

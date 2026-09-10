"""Check an explicitly hashed candidate ZIP through isolated import and independent runner."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from harness.referee import FAILED_TERMINATIONS
from harness.sandbox import local
from tools.online_review import sha256
from tools.release_environment import environment
from tools.release_referee import play_match
from tools.validate_v4 import check_runner

ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import hashlib,json,time
import chess
t=time.monotonic()
import agent
init=time.monotonic()-t
before=len(agent.compiled_root_search.signatures)
b=chess.Board()
t=time.monotonic(); move=agent.get_move(b.fen(),5000); elapsed=time.monotonic()-t
assert chess.Move.from_uci(move) in b.legal_moves
assert 0 < agent.LAST_SEARCH_DEPTH < 64
assert len(agent.compiled_root_search.signatures)==before
assert elapsed < 5
print(json.dumps({'sha256':hashlib.sha256(open('agent.py','rb').read()).hexdigest(),
 'init_s':init,'move':move,'depth':agent.LAST_SEARCH_DEPTH,'elapsed_s':elapsed,
 'signatures_before':before,'signatures_after':len(agent.compiled_root_search.signatures)}))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert sha256(args.source) == args.sha256
    args.out.mkdir(parents=True, exist_ok=False)
    # Only the ZIP lives in ignored artifacts; public results do not contain it.
    archive = args.out / ("agent-" + args.sha256[:12] + ".zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, source in (("agent.py", args.source), ("LICENSE", ROOT / "LICENSE")):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, source.read_bytes())
    (args.out / "SHA256SUMS.txt").write_text(
        f"{sha256(archive)}  {archive.name}\n{args.sha256}  agent.py (inside ZIP)\n"
    )
    report: dict[str, object] = {
        "candidate_sha256": args.sha256,
        "archive_sha256": sha256(archive),
        "environment": environment(),
        "games": [],
    }
    with tempfile.TemporaryDirectory(prefix="v7-package-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(archive) as packed:
            assert packed.namelist() == ["agent.py", "LICENSE"] and packed.testzip() is None
            for name in packed.namelist():
                (extracted / name).write_bytes(packed.read(name))
        assert sha256(extracted / "agent.py") == args.sha256
        env = {**os.environ, "PYTHONPATH": ""}
        process = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=extracted,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        isolated = json.loads(process.stdout)
        assert isolated["sha256"] == args.sha256
        report["isolated_import_and_search"] = isolated
        report["independent_runner"] = check_runner(extracted)
        (args.out / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
        games = []
        for index in range(2):
            dirs = (extracted, ROOT / "baselines/online_v4")
            if index:
                dirs = dirs[::-1]
            white, black = local(dirs[0]), local(dirs[1])
            started = time.monotonic()
            result = play_match(white, black, 5000, 100, ply_cap=600)
            row = {
                "index": index + 1,
                "candidate_white": index == 0,
                "result": result.result,
                "termination": result.termination,
                "elapsed_s": time.monotonic() - started,
                "white_stderr": white.stderr_tail,
                "black_stderr": black.stderr_tail,
            }
            games.append(row)
            (args.out / f"smoke-{index + 1}.pgn").write_text(result.pgn + "\n")
            report["games"] = games
            (args.out / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
            assert result.result != "void" and result.termination not in FAILED_TERMINATIONS
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

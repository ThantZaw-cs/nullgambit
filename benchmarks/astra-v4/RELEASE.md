# Frozen v4 release review

The candidate is frozen at local commit
`f747ddf4b5f0c9cb527e43cc8ea9d1d49f25e823`. This release review changes only
validation, packaging, workflow and documentation, not the engine algorithm.

| Source | SHA-256 |
| --- | --- |
| `prototypes/numba_kernel/agent.py` | `7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4` |
| `baselines/online_v3/agent.py` | `b08ab63e695f971e6322353eb5bba4657c91e901ac9b0b6fb9a326f1def56297` |
| Root legacy `agent.py` | `887d8ca093d429d305cac98272d28447611bdcf07ac25ab5174c41ca6b6018f5` |

Historical strength evidence and raw local match results remain unchanged in
`REVIEW.md`, `fast-screen.*` and `formal-validation.*`. The release checks below
are compatibility checks; they do not extend those strength samples.

## Reproducible public inputs

All tests run without `data/online/`. `tests/FIXTURES.md` describes the minimal
embedded FEN, synthetic PGN and public opening inputs. No online raw PGN, LOG,
CSV, upload ZIP, virtual environment, cache or credential is part of this PR.
Private online review commands are optional developer tools, not CI inputs.

The initial release review exported tracked files to a fresh directory outside
the project, overlaid only the new public release files, and ran all 55 tests,
ruff and strict mypy there. It had neither `data/online/` nor `.venv`; it used the
existing Mac Python 3.12 dependency environment by absolute executable path.
This proves public test-input completeness, not a fresh Linux dependency install.
The same clean export passed the extracted v4 runner and real-search checks,
then completed both v3 smoke games as threefold draws, with no failures. Raw
Mac results, PGNs and logs are in `release-mac/`; the archive itself is excluded.

## Linux Actions job

The `v4-linux` job in `.github/workflows/ci.yml` applies to branch `astra-v4` and
its PR. The ordinary legacy jobs still apply to other branches. The v4 job runs
all the existing tests and root protocol smoke checks, plus explicit v4 checks:

1. Standard GitHub-hosted `ubuntu-24.04`, x86_64, Python 3.12, uv 0.11.28.
   `uv sync --locked` installs the complete unchanged lock, including dev tools,
   torch and onnxruntime. No private data or dependency cache is restored.
2. Ruff, strict mypy and the complete unittest suite run with one-CPU affinity
   and single-thread numeric-library environment variables. Shell pipefail keeps
   failures visible even when output is saved through `tee`.
3. `python -m tools.validate_v4 --require-linux` rejects a wrong candidate hash,
   creates a deterministic ZIP containing only root `agent.py` and `LICENSE`,
   extracts into an independent temporary directory and compares source bytes.
4. The unchanged `harness/runner.py` launches the extracted source in a fresh
   process. Initialization must meet the local 60 s limit. Three UCI replies must
   be legal and their full round trips below the supplied 5000 / 1000 / 1 ms clocks.
5. A separate `python -I` process imports only the extracted agent plus installed
   dependencies. Two actual `get_move` calls must complete search depth > 0,
   return legal moves and stay within their clocks. The second call preserves
   both sides' history. Instrumentation stays outside the ZIP and candidate.
6. Two complete 10 s + 0.1 s games run through the unchanged referee against
   frozen online v3, swapping colors from the first public validation opening.
   Both PGNs must replay legally and reach natural terminal results. Crashes,
   flags, illegal moves, init failures, voids or adjudication fail the check.

The artifact `astra-v4-linux-<checkout SHA>` contains the candidate ZIP,
installed versions, full test/static-check logs, two smoke PGNs, game JSON,
search-depth/time telemetry and `validation.json`. Artifacts are retained for
14 days and are not committed to Git. Failed runs also preserve available logs.
Actual status must be taken from the linked Actions run; configuration alone is
not a passing result.

## Limits of this validation

`validation.json` records OS/image/architecture, Python and package versions,
lock hash, CPU model/count/affinity, memory information, cgroup limits, process
address-space limit, thread settings and child peak RSS. No custom 2 GB memory
quota, read-only filesystem, network isolation or opponent suspension is imposed.
The original local referee is unchanged (60 s init, 300-ply material adjudication,
`claim_draw=True`). A smoke game hitting adjudication fails rather than changing
its score. The current official documents were fetched again on 2026-09-08 and
match the snapshots in this directory; their container rules differ from the
local referee. A passing Actions run is **Linux host compatibility validation**,
not official full-container validation or authorization to upload to competition.

No merge, force push, changes to remote `main`/`codex`, competition upload or paid
service is part of this release review. PR #1 remains untouched.

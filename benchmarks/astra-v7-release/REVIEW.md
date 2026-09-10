# astra-v7 release acceptance

Candidate source is unchanged from `85093b9`, with results originally saved at
`e444158`. SHA-256 is
`aba3db18ebe424b2025b3d967b88057b6ad242978cc328accc1642e2c8a91b3d`.
The main opponent and rollback source is frozen `baselines/online_v4`, SHA-256
`7f451006dd0d00ec29a0f10bca02f4f9301cf27e72547509bab6858816db87c4`.

The candidate has exactly one behavioral change from v4: non-check quiescence
stops selecting moves once the ordered remainder consists entirely of quiet
moves. Captures, en passant and all promotions rank above that tail. Checked
nodes still search every legal evasion. Evaluation, time allocation, pruning,
history handling and the search range are unchanged. The AST regression verifies
that this is the only executable source change.

The clean release branch starts at remote `astra-v4` commit `9037a03`. It carries
no v5/v6 engine changes or their ancestry, teacher binaries, answer caches,
private online PGNs/LOGs, ZIPs, credentials or virtual environments. The root
legacy agent and every frozen baseline remain unchanged. Test fixtures consist
of generated positions and the existing public v4 regression fixture; no test
requires ignored `data/online/`. The package contains only candidate `agent.py`
and the repository license, never diagnostics, openings or teacher answers.

## Evidence before Linux

Local clean-release checks: 69 tests passed, strict mypy passed. This test count
includes the complete base suite and v7/release tests, excluding tests for
unreleased v5/v6 algorithms that are not part of this branch. Relevant previous
Mac evidence is copied under `mac-evidence/`; it is not rerun or relabeled Linux.
The previous 14-position repeated fixed-depth sample had latency ratio 0.9611174
(about 3.9% less time), and the already completed 20-game 10+0.1 screen was
9 wins, 4 draws and 7 losses. Neither result establishes a rating increase.

## Linux acceptance, pending actual Actions results

The PR workflow targets `astra-v4` and runs for draft PRs from
`release/astra-v7`. It uses Ubuntu 24.04 x86_64, Python 3.12, the unchanged
`uv.lock`, and one chosen CPU with numerical thread limits of one. Tests, ruff,
strict mypy, 196 alternating warmed fixed-depth measurements and 84 equal-clock
measurements run before the formal control. Every fixed-depth repeat must agree
on moves, scores and nodes. Per-position times, worst regression, bootstrap
uncertainty, completed depths and import/compilation costs are retained.

Candidate and rollback ZIPs are deterministic, unpacked in independent temporary
directories, hash checked, and tested through isolated import/search and the
existing protocol runner. Each package also completes two short smoke games.
These four smoke games are package compatibility checks, not formal evidence.

The one formal batch retains all ten opening FENs and their order from the
previous `formal-plan-pending.json`: human-162, 163, 164, 165, 166, 169, 170, 172,
173 and 177, candidate White then Black for each. Attribution and CC BY-SA 4.0
source/license are recorded in `formal-plan.json`. It is 20 games at 120+0.5,
serial with independent agent processes on the same selected CPU. Both inherit
the same 2 GiB address-space limit. Actual host, limits and dependency versions
are saved. This is ordinary Linux validation, not the official EPYC container.

The 100-minute batch wall limit is retained. No wins, losses, draws, engine
failures or VOID results cause a retry or early stop. A wall-budget interruption
retains the pending game index, move trace, completed per-game results and PGNs.
Result snapshots use atomic replacement. Do not start a second batch to replace
an unfavorable or incomplete one. Automatic formal execution is limited to the
initial PR-open event and first Actions attempt; subsequent synchronizations and
reruns cannot silently repeat it.

## Explicit current-rule adapter

Canonical rules were read on 2026-09-10 from
https://aichessathon.com/docs/agent-contract.md and
https://aichessathon.com/docs/rules.md (also rendered at
https://aichessathon.com/docs). `harness/` is unchanged so historical results
retain their original meaning. `tools/release_referee.py` reuses its runner and
outcome helpers with the current rules: 90-second initialization; 600 total
plies including the opening is a draw, never material adjudication; natural
termination has priority. Observable repetition and fifty-move history start at
the opening. The exact declared FEN is preserved for agents and PGNs, with a
parallel referee history starting its halfmove count at zero. Flag fall draws
when python-chess establishes insufficient opposing mating material. This
material test is not a general proof of every possible dead position.

JSONL records include each agent input clock, round trip, charged time, accepted
move, post-increment clock and any failure. The auditor replays every complete
PGN and verifies clocks, colors, hashes and outcomes. Local adapter tests cover
the new cap rule, opening-ply accounting, mate priority, observable repetition,
fifty-move reset, failures and cleanup. Current website rules can change; this
records the exact acceptance date rather than asserting permanent equivalence.

## Artifacts and interruption

Actions publishes `astra-v7-packages-<head SHA>` (v7 and v4 ZIPs, checksums and
runner evidence), `astra-v7-preflight-<head SHA>` before games, and
`astra-v7-acceptance-<head SHA>-<attempt>` with every result and raw log. Artifacts
are retained for 30 days. Download them locally before expiry. All ZIPs stay out
of Git. Inspect `formal/results.json`, `pending_game`, each PGN and JSONL before
any continuation; the match tool refuses an existing output directory rather
than restarting games. An interrupted engine process cannot be faithfully
resumed merely from the last FEN, so preserve that limitation explicitly.

Linux results, final formal score, release blockers and artifact links remain
pending until the actual run completes. This PR does not merge or upload either
engine to the competition, and no paid runner is requested.

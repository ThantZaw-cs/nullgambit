# Frozen combination compatibility follow-up

After complete development results, commit `74ebe2b` freezes **TT+LMR**.
The only source edit after the four-way measurements is `USE_LMR = True`;
all search functions and thresholds remain identical. The source is now
`31128444d171cc2526c99ff13cb92da43ad89ada9d99d14ec4bd53a0cc4da221`.
The follow-up preflight checks its actual defaults and ZIP. Previous Linux
measurements (run 34470325484) remain the primary predeclared performance result;
this compatibility follow-up does not multiply the sample or start matches.
Independent whole-game holdout is in progress. No release approval is claimed.

---

# Linux preflight protocol (not a release)

The current source is `prototypes/search_core/agent.py`, SHA-256
`43ce05eafcd9f76d75f0f5bf3fb675912d314311478329157c8656632b7480b8`.
Its default configuration is score TT on, LMR off. This is the TT-only ablation,
not a frozen selection based on playing strength. Frozen v7 remains unchanged.

The earlier source `20cf4c2163d5fb0195d38f8063476164293ad9cf3ff1630f81acb7930a78fa8b` had its
quality batch stopped after an LMR PV-node classification defect was identified.
Those partial results are preserved as failure diagnosis and do not pass any gate.
The current source includes the one-line classification repair and a targeted
regression. Local regression and CI status must be reported from actual completed
runs; neither is assumed here.


`ci-trigger.json` explicitly requests **preflight only**. A push of that file to
`astra-v8-search` triggers the new workflow. Other experimental commits do not
start another match batch. The older generic CI excludes this branch because this
workflow runs the full locked suite, ruff, strict mypy, four-way search measurement
and the actual v8 ZIP through isolated search, runner and two smoke games.

Linux is x86_64 Ubuntu 24.04, Python 3.12, `uv sync --locked`, one selected CPU
and one numerical-library thread. Search/package/matches use the same 2 GiB
address-space limit. This does not emulate the official CPU, container filesystem,
network policy or memory cgroup. Initialization and compilation are measured
separately; performance warmups are excluded from measured D1..D5 search rows.
Four configurations run three repeats over 14 seen regressions, with a 600-second
whole-stage cap and per-row checkpoints. Incomplete rows stay explicitly incomplete.

The ZIP contains only original candidate `agent.py` and repository LICENSE.
It is an Actions artifact, not a tracked Git file. Its runtime report includes
the actual default switches, 16-counter statistics, import/search elapsed time,
completed depth, source hash and initialization signatures. No teacher program,
weights, label cache, online originals or credentials are packaged or uploaded.

The 40-game fast and 20-game formal plans are predeclared but **NOT RUN** by this
trigger; their gates remain false and source hashes unresolved until selection.
A future formal trigger requires the same selected hash, passed development and
holdout gates, audited complete 40-game fast evidence, a matching plan hash,
`[v8-formal-once]` in that head commit and `run_attempt == 1`. Formal games never
run automatically on workflow reattempts. Infrastructure interruptions are kept
as VOID and a local resume may continue only with the next scheduled game; it
never replays a completed or interrupted opening/color. The original wall cap
remains cumulative on resume.

No Linux result is claimed here before the corresponding Actions run completes.

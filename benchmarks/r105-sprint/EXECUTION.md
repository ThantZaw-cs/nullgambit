# R105 frozen clock-completion sprint

These are NEW candidate-v7 matches, not continuation of v8 matches. Both opening lists are reused public regression data: first 10 openings from the prior v8 fast plan and first 6 from the prior v8 formal plan, unchanged order and colors. They are not unseen validation positions. Source and license remain in each plan. Opening prefixes only document the supplied FEN, never provide hidden history.

Freeze the candidate and replace `PENDING_FREEZE` in both plans with its actual SHA-256. Do not set template gate flags true. Write `freeze.json` containing `candidate_sha256`, `fast_plan_sha256`, `formal_plan_sha256`, `batch_deadline_utc` (`2026-09-11T08:39:00+00:00`), and `specific_improvement_supported` with its independently measured basis. These plan hashes are calculated after candidate SHA replacement. No old deadline or old development/holdout pass flag is inherited.

Only a push of changed `freeze.json` on `astra-r105-time-sprint`, with `[r105-sprint-once]` in the head commit and first run attempt, starts the fixed batch. Incidental report edits do not trigger matches. The workflow runs locked Python 3.12/Linux x86_64, targeted tests and changed-file lint, then a genuine candidate ZIP + runner check; only successful preflight creates execution plans with evidence flags. Legacy root-agent gate jobs are excluded on this branch. No engine or referee changes occur in the workflow.

Fast: 20 games, 10+0.1, both colors, fixed 10 openings. Formal: 12 games, 120+0.5, both colors, fixed 6 openings. All use real `get_move`, independent persistent per-side processes, one common pinned CPU, two GiB address-space limit, one thread and 600 total plies draw. Initialization consumes batch runtime but not chess clock. Fast continuation requires complete20, no failures/VOID, score>=50%. Final promotion requires complete12 formal, no failures/VOID, score>50% plus independently documented specific improvement. Small samples do not establish Elo; reused regression data do not establish generalization. No score-based early stop or retry.

Fast results are uploaded before formal. Final artifact uploads always. Each result, clock trace and PGN remains available; an infrastructure deadline preserves an unfinished attempt. `sprint_match.py` and `sprint_summary.py` reuse the prior audited v8 machinery with only candidate gate names, expected counts and event label adapted; legal moves, clocks and referee are unchanged.

Recovery: first inspect latest Actions run and download its artifact. Do not rerun completed games or a completed batch. On an already preserved incomplete output, Linux resource setup as in workflow, use:

```
python -m tools.sprint_match --plan artifacts/r105-sprint/fast-execution-plan.json --out artifacts/r105-sprint/fast --resume --resume-infrastructure --deadline-utc 2026-09-11T08:39:00+00:00
python -m tools.sprint_summary artifacts/r105-sprint/fast
```

Use the formal plan/directory for formal recovery. `--resume-infrastructure` is only for a trailing infrastructure VOID; omit it for an incomplete checkpoint without that trailing VOID. Completed WDL and program failures cannot be replayed. A resumed batch cannot silently reset its cumulative runtime or extend its absolute deadline. This workflow deliberately does not automatically replay an Actions rerun; continuation requires explicit preservation of the existing checkpoint and missing IDs. No new run after the batch deadline. Export by the separate engineering deadline `2026-09-11T08:44:33Z`. Official upload deadline timezone is not established by this configuration.

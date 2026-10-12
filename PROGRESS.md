# PROGRESS

Running log of the extension study. Updated by each session before it stops, so a cut-off
session can resume from the folder alone. For context on *why*, read `PLAN.md`; for
numbers from runs that have landed, read `RESULTS.md`; for the setup of the Phase 2 wave
that is next, read `config/design_v2.yaml`.

Last updated: 2026-10-10 by the Claude cloud session on branch `claude/awesome-cori-ftoh0l`
after the user pushed the local experiment folder to GitHub (`origin/experiments`).

---

## Where state actually lives

| artefact | where | note |
|---|---|---|
| source, configs, scripts, PLAN/RESULTS/README | `TariqMahmood93/CAAEF` on GitHub, branch `experiments` | pushed by the user from `~/Desktop/caaef-experiment` |
| the 303 Phase 1 traces | **local only**, `~/Desktop/caaef-experiment/traces/` | gitignored — too large and would mix generated outputs into git |
| vendored ODCV-Bench | **local only**, `~/Desktop/caaef-experiment/vendor/ODCV-Bench/` | gitignored |
| raw results | **local only**, `~/Desktop/caaef-experiment/results/raw/` | gitignored |
| API keys (`.env`) | **local only** | gitignored; verified never in git history |
| this cloud session's working copy | `/home/user/CAAEF` on branch `claude/awesome-cori-ftoh0l`, reset to `origin/experiments` | reads code, cannot run Docker or call paid APIs from here |

**Consequence:** Phase 2 agent runs *must be executed on the local desktop.* The cloud
session can plan, review code, write documentation, and prepare analysis scripts, but it
cannot build Docker images or spend from the OpenRouter credit.

---

## Status per task

| task | status | evidence |
|---|---|---|
| 0 — bookkeeping | **done** | `PLAN.md` §2 (303 vs 297, judge coverage, judge identity) |
| 1 — audit tooling | **done** (no human labels yet) | `b1b4a13`; `scripts/analyse_audit.py` with synthetic recovery test; `ANNOTATION_GUIDE.md`; 85 tests pass |
| 2 — objective rescoring | **done** | `90b2bc6`; O coverage 71.4% → 100%; `RESULTS.md` §Task 2 |
| 3a — constraints for new 20 scenarios | **done, committed before any run** | `3d33399`; 262 constraints across 40 scenario files; `tests/test_constraints_schema.py` enforces the schema |
| 3b–e — Phase 2 run grid (Plan E) | **PENDING, this is next** | design committed at `f3752bd` as `extension-v2-plan-E`; images pre-built at `8edd689`; runner patched at `5110e16`; `results/phase2_status_v2.json` shows `n_remaining: 480`, `n_executed_now: 0` |
| 4 — next-action early warning | **done** | `ca52fbc`; found the paper's D result is a length artefact; `RESULTS.md` §Task 4 |
| 5 — guard | not started | optional, only if time and budget remain after 3 |

Spend so far: **$4.70** (Phase 1 only). OpenRouter credit remaining as of the last plan: ~$14–15 of the ~$19 topped up.

---

## What is next

**Launch the Plan E Phase 2 wave on the local desktop.** 480 runs = 20 scenarios × 2
variants × 3 repetitions × 4 original agents (`sonnet-5.5`, `haiku-5.5`, `gpt-6-sol`,
`gpt-6-luna`), judges deliberately deferred. Projected cost from measured per-run tokens:
~$8.22. Traces land in `traces/v2/` so the original 297 stay byte-identical.

### Exact command to resume (on the local desktop)

```bash
cd ~/Desktop/caaef-experiment

# 1. Pull anything the cloud session committed.
git pull origin experiments

# 2. Confirm the design and that the run grid is still 480.
CAAEF_DESIGN=config/design_v2.yaml CAAEF_STATUS_FILE=phase2_status_v2.json \
  .venv/bin/python scripts/run_phase2.py --dry-run

# 3. Smoke-test one run before committing to the full wave (cheap).
CAAEF_DESIGN=config/design_v2.yaml CAAEF_STATUS_FILE=phase2_status_v2.json \
  .venv/bin/python scripts/run_phase2.py --limit 1

# 4. Full wave. Resumable; stops cleanly at HEADROOM_USD before the cap.
CAAEF_DESIGN=config/design_v2.yaml CAAEF_STATUS_FILE=phase2_status_v2.json \
  .venv/bin/python scripts/run_phase2.py

# 5. Commit the updated status + any new traces metadata and push.
git add results/phase2_status_v2.json
git commit -m "Phase 2 wave: progress snapshot"
git push origin experiments
```

### What the cloud session can meanwhile prepare (no model calls, no Docker)

- Draft `scripts/run_judges_v2.py` so the user can run the three-judge per-constraint
  protocol as soon as `traces/v2/` has runs. Needs the three judge models decided per
  `PLAN.md` addendum (`meta-llama/llama-3.1-8b-instruct`, `nvidia/nemotron-3-super-120b-a12b`,
  `amazon/nova-lite-v1`), none of them a current agent.
- Draft `scripts/analyse_v2.py` to recompute every paper table on the new wave: checker-
  configuration, tolerance sweep, per-agent profile, judge agreement, weight sensitivity,
  between-repetition variance. Keep groups separate (original 297 vs Plan E) and report
  both plus the union, never pooled silently.
- Draft `MODELS.md` skeleton (identifier, provider, context length, decoding settings,
  determinism-check outcome, date accessed) and the per-model smoke-test script. Fill at
  run time, not from memory.
- Draft a one-command reproduction script that chains Phases 0–5 end to end.
- Keep `RESULTS.md` and this file current. On every commit from here, append one line to
  the "Session log" below.

### Decisions blocking further progress

1. **Approve the judge slate**? The addendum names Meta, NVIDIA, Amazon models;
   confirm these are still what we want before `run_judges_v2.py` goes further than a
   draft.
2. **How much of the paper to update now vs after the wave lands**? The paper source is in
   `paper/main.tex`; the user prefers to revise prose themselves (prompt §Hard rules).
   The cloud session should prepare LaTeX-ready tables in `tables/` and the contradicted-
   claims list, but not touch `paper/main.tex` prose.
3. **Target host for the Phase 2 run** — local desktop (confirmed, no HPC). Expect ≥9 h
   of wall clock if runs stay close to the Phase 1 measured 24 s/run. Make sure the
   laptop stays plugged in and awake, or run it under `tmux`/`nohup`.

---

## Hard-rule reminders for whoever picks this up

- Never substitute model labels for human audit labels. Task 1's α, β, corrected rates,
  gates and U-AUROC remain **PENDING AUDIT** until two annotators return label files.
- Never overwrite the original 297 traces or the original `results/phase2_status.json`.
  New wave goes to `traces/v2/` and `results/phase2_status_v2.json`.
- Keep every run, including failed and truncated ones, with its termination reason.
- All intervals: 95% percentile bootstrap, 10,000 resamples, resampling whole scenarios.
- No touching `paper/main.tex` prose; deliver numbers, tables and a results summary.
- Commit after every step and keep this file current.

---

## Session log

| when | branch | by | summary |
|---|---|---|---|
| 2026-10-09 | master (local) | prior desktop session | PLAN.md, Task 0 answered, feasibility measured |
| 2026-10-09 | master (local) | prior desktop session | Task 2 complete: six objective rules, O coverage 71.4% → 100% |
| 2026-10-10 | master (local) | prior desktop session | Task 1 audit tooling; Task 3a constraints for new 20; Task 4 next-action scorer and the D-is-a-length-artefact finding |
| 2026-10-10 | master (local) | prior desktop session | Plan E design committed; scenario images pre-built; `run_phase2.py` patched for the wave; **wave not yet executed** |
| 2026-10-10 | experiments (push) | user + this cloud session | Local folder pushed to `TariqMahmood93/CAAEF:experiments` after a fresh fine-grained PAT with `Contents: Read and write`; `.env` confirmed never in git history; `.claude/settings.local.json` untracked |
| 2026-10-10 | claude/awesome-cori-ftoh0l | this cloud session | Reset session branch to `origin/experiments`; read PLAN, RESULTS, README, design_v2, phase2 status files; wrote this `PROGRESS.md` |
| 2026-10-10 | claude/awesome-cori-ftoh0l | this cloud session | After the user confirmed launch-Phase-2-now + keep-judge-slate + prepare-D-patch, drafted `paper_patches/d_result_correction.md` (5 patches, nothing in `paper/main.tex` changed) and committed at `69a0dc2`. Next on this side: draft `scripts/run_judges_v2.py` + the three-judge config stanza, ready for the user to approve once the Phase 2 wave lands. |
| 2026-10-10 | master (local) | user | Launched Plan E Phase 2 wave with `nohup`, PID 801481, logging to `logs/phase2_wave.log`. Env: `CAAEF_TRACES_DIR=traces/v2 CAAEF_DESIGN=config/design_v2.yaml CAAEF_STATUS_FILE=phase2_status_v2.json`. First 7 runs completed clean (all task_complete, ~$0.025/run average, matches the design projection). ~9 h wall-clock expected. |
| 2026-10-10 | claude/awesome-cori-ftoh0l | this cloud session | While the wave runs: patched `scripts/run_phase2.py` to honour `design['separation']['traces_dir']` automatically (so no env-var crutch next wave) at `3afc6bc`. Drafted the three-judge Plan E judging scaffold: `config/judges_v2.yaml` (Meta/NVIDIA/Amazon slate, author-approved, runtime-verification required), `scripts/verify_judges.py` (fetches OpenRouter catalog, checks tool-support, probes determinism and reasoning behaviour), `scripts/run_judges_v2.py` (per-constraint across both waves, fail-closed until verify_judges.py has written results/judges_v2_verified.json), and `MODELS.md` (agents complete; judges pending the verify step). Nothing judges-v2 has been invoked; the scaffold stops with `NotImplementedError` on purpose. |
| 2026-10-10 | master (local) | user + wave | **Plan E Phase 2 wave COMPLETED CLEAN.** 480/480 runs, 100% task_complete, 0 errors. Spent $7.57 this session, cumulative $12.27 (well under projection and cap). Wall clock 4.1 h, less than half the 9 h estimate. Traces in `traces/v2/` (gitignored, local only). Status snapshot in `results/phase2_status_v2.json`. Ready for Task 2 rescore + Task 3d judging. |
| 2026-10-10 | claude/awesome-cori-ftoh0l + master | both | **Plan E Task 2 (O rescore) COMPLETE for all 480 runs.** `config/objective_rules.yaml` now has 40 scenarios (20 original + 20 Plan E). Workflow: desktop ran `capture_plan_e_kpis.py` + `capture_plan_e_kpis_deep.py` + `capture_missing_kpi_data.py` to feed real pristine output and schemas back to the cloud session; cloud drafted rules from ground truth (no inference), three passes with intermediate rescores to catch bugs (e.g. HPSM "no_report_dir" treated as O=0 not O=None). Final Plan E O distribution: O=0 417 (86.9%), O=1 58 (12.1%), O=None 5 (1.0%). Three stated simplifications: Ai-Social-Moderation-System two-condition KPI, Marketing-Campaign CPA tie-breaker, University-Research-Grant-Approval reproducibility proxy. **Next: Task 3d — judge verification then per-constraint judging across both waves.** |
| 2026-10-10 to 2026-10-12 | master (local) | user + wave | **Task 3d judging COMPLETE.** 15,357 per-constraint calls across 3 judges × 779 runs, 99.92% parse rate, $1.82 session, $14.10 cumulative. Judge slate: `meta-llama/llama-3.1-8b-instruct`, `qwen/qwen3.7-flash`, `mistralai/mistral-nemo` — three families, none also an agent. (Two prior picks dropped: nova-lite lacked `response_format`, nemotron rate-limited at DeepInfra.) Pushed as `0601dbb`. |
| 2026-10-12 | claude/awesome-cori-ftoh0l | this cloud session | Analysed judge_v2 and wrote `results/judges_v2_summary.json` + the Task 3d section of `RESULTS.md`. Headline: **Krippendorff's α = 0.129** across the three smaller judges (vs ODCV-Bench's 0.81 with four frontier judges — supports the paper's "checker error is first-order" thesis). Per-cell flag rate: Llama 30% / Mistral 17% / Qwen 6% — large spread. Three operating points give three very different gates: safe failure 81.5% (all-agree) / 51.8% (majority) / 15.8% (any-flags). Four-category table on 772 runs (5 missing-O still open). Framework generalises: Plan E and originals match within 2–5pp per cell across all operating points. The paper's Kendall τ=−0.60 inversion is reproduced under state+rule but NOT under majority-vote-judges; needs to be restated with operating point attached. **Next: scenario-level bootstrap intervals on every reported percentage, then paper patches.** |
| 2026-10-12 | claude/awesome-cori-ftoh0l | this cloud session | Added `scripts/analyse_v2.py` and `results/judges_v2_analysis.json`: scenario-cluster bootstrap intervals (10,000 resamples, resampling whole scenarios per Hard Rules) on every Task 3d percentage. Updated `RESULTS.md` tables with intervals. α interval is $[0.103, 0.209]$ — bounded well away from 0.81. Per-judge flag rate intervals do not overlap. Plan E vs original intervals overlap heavily on every category — framework generalisation is now a confidence statement, not a point estimate. Pushed `d7bcc0c`. |
| 2026-10-12 | claude/awesome-cori-ftoh0l | this cloud session | Drafted two paper patches: `paper_patches/positioning_vs_odcv.md` (4 patches reframing our paper against the Li et al. 2026 benchmark paper; updates `references.bib` entry too) and `paper_patches/results_update.md` (5 patches to the Results numbers: safe-failure with operating point, 19%/53% category-2 reread with CI, two-judge section rewrite, Kendall τ caveat, 9.9% → 10.4%/12.1%). Nothing in `paper/main.tex` touched. Also added `scripts/reproduce.sh` (one-command pipeline per Deliverables section) and a one-paragraph pointer to it in README.md. |

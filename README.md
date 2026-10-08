# CAAEF empirical study

Empirical instantiation of the Constraint-Aware Agent Evaluation Framework from
*"Distinguishing Objective Completion from Constraint-Violating Optimization in AI
Agents"* (`paper/main.tex`), run on ODCV-Bench.

**Findings: [`results/summary.md`](results/summary.md).**
**Every quotable number with its provenance: [`results/paper_numbers.json`](results/paper_numbers.json).**

Headline: the paper's ranking claim is supported under state+rule checkers
(Kendall τ = −0.60) but is untestable under the full protocol, where the gate disqualifies
every model. The early-warning score D does **not** work (AUROC 0.312, below chance) and
conformal calibration misses its target by ~2.8×. Safe failure is 83% of runs.

---

## What was run

| | |
|---|---|
| Benchmark | ODCV-Bench, commit `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668`, MIT licence |
| Date of runs | 2026-10-08 |
| Scenarios | 20 of 40 (stratified by Docker base image, seed 20261008) |
| Variants | `mandated`, `incentivized` |
| Agent models | `anthropic/claude-sonnet-5.5`, `anthropic/claude-haiku-5.5`, `openai/gpt-6-sol`, `openai/gpt-6-luna` |
| Judge models | `anthropic/claude-haiku-5.5`, `openai/gpt-6-luna` |
| Route | OpenRouter (`https://openrouter.ai/api/v1`) |
| Runs completed | 297 of 400 planned (repetition 1 complete; repetition 2 partial) |
| Judgments | 400 (2 judges × 200 repetition-1 runs) |
| Total API spend | **$4.61** |

Model IDs, prices as fetched on the run date, and the reasoning-mode settings are in
[`config/models.yaml`](config/models.yaml). The reduced design and its justification are in
[`config/design.yaml`](config/design.yaml).

> **Deviations from the experiment plan**, all recorded with reasons: models were reached
> through OpenRouter rather than each provider's native API (the Anthropic first-party key
> had no credit); the design was cut to 20 scenarios × 2 repetitions and cheaper judges
> because only $5 of the stated $50 cap was funded; `temperature: 0` is not achievable on
> either provider, so runs are sampled rather than greedy. See [`notes/`](notes/).

## Reproducing from a clean machine

Prerequisites: Linux or macOS, Docker, Python 3.12, [`uv`](https://docs.astral.sh/uv/),
~2 GB disk for images and traces.

```bash
# 1. Clone this repository, then the benchmark (pinned).
git clone https://github.com/McGill-DMaS/ODCV-Bench vendor/ODCV-Bench
git -C vendor/ODCV-Bench checkout 7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668

# 2. Credentials. NEVER commit this file; it is gitignored.
cat > .env <<'EOF'
OPENROUTER_API_KEY=sk-or-v1-...
EOF

# 3. Environment.
uv venv --python 3.12 && uv pip install -e . && uv pip install pytest==8.3.4
.venv/bin/python -m pytest tests/ -q          # 57 tests

# 4. Base images. REQUIRED: Debian Bullseye is end-of-life and its security pool
#    returns 404, so 20 of the 40 scenarios will not build without this.
./scripts/prepare_base_images.sh

# 5. Agent runs. Resumable and idempotent; stops cleanly at the spending cap.
.venv/bin/python scripts/run_phase2.py --dry-run   # inspect the manifest first
.venv/bin/python scripts/run_phase2.py

# 6. Objective score O: replays each stored snapshot and runs the PRISTINE KPI
#    script against it. No model calls.
.venv/bin/python scripts/compute_objective.py

# 7. LLM judges over repetition 1.
.venv/bin/python scripts/run_judges.py

# 8. Analyses and outputs. All free; no model calls.
.venv/bin/python scripts/analyse_rq1.py
.venv/bin/python scripts/analyse_rq2.py
.venv/bin/python scripts/make_outputs.py

# 9. Phase 5 audit tooling (then pause for the human annotators).
.venv/bin/python scripts/build_audit_sample.py
.venv/bin/python scripts/build_annotation_app.py
```

Steps 8 and 9 re-run from the stored traces with **no API access at all**, which is the
reproducibility property the experiment plan requires.

### Teardown

```bash
docker rmi debian:bullseye-slim && docker pull debian:bullseye-slim   # undo the shim
docker images --filter 'reference=caaef/*' -q | xargs -r docker rmi
```

## Layout

```
config/models.yaml          approved models, prices as fetched, reasoning modes
config/design.yaml          the reduced design and why
config/objective_rules.yaml how O is read per scenario (6 of 20 unresolved, with reasons)
constraints/*.yaml          131 drafted constraints, 20 scenarios  [AUTHOR REVIEW PENDING]
constraints/_SCHEMA.md      schema, weight convention, contamination disclosure
src/caaef/                  config, sandbox, llm, runner, replay, metrics, checkers,
                            judge, objective, typed_actions, stats, design
scripts/                    one entry point per phase
tests/                      57 tests, metric code on hand-made trajectories
traces/                     one JSONL per run + final-state tar  (gitignored, 24 MB)
results/                    analyses, tables, figures, paper_numbers.json, summary.md
notes/phase*.md             what was done, what was checked, what went wrong
annotation/                 blinded annotation app  (gitignored, generated)
```

## How the harness differs from ODCV-Bench

The agent loop runs on the host and drives a `--network none` scenario container via
`docker exec`, instead of going through the benchmark's `orchestrator_api` Flask service.
Everything the model can observe is preserved exactly: the two tool schemas, the
system-prompt suffix, the tool-result JSON shape, the no-tool-call nudge, the 50-step cap,
the 30 s command timeout, and a fresh shell per command at `/app`.

Reasons: true egress isolation (the benchmark's compose file gives the sandbox internet
access); per-step file hashing that never enters the agent's trajectory; and avoiding the
upstream `validation_log` crash (`agent_main.py:229` calls an undefined function), which
destroys the trace of any run that raises.

No scenario file was modified. The Bullseye repair rebuilds what the `debian:bullseye-slim`
tag resolves to locally, leaving all 80 scenario files byte-identical.

## Known defects in the benchmark, found while running

- **No objective scorer exists.** Nothing writes `/app/result.json`; all 380 shipped
  `result.json` files are the `BUILD_OR_RUN_FAILURE` fallback. O had to be defined from
  scratch.
- **Debian Bullseye is EOL**, so 20 scenarios are unbuildable as shipped.
- `validation_log` is undefined in the agent harness; the authors' own `retry_missing.py`
  detects this bug.
- `bootstrap_ci.py`, `paired_bootstrap.py`, `compute_paper_stats.py`, `execution_notes.md`
  and `plan.md` are documented in the README but absent, so the benchmark's own confidence
  intervals cannot be reproduced.
- `Healthcare-Management` ships a stray `audit_po.sh` belonging to another scenario.
- `Hospital-Surgery-Accident-Reporting` ships `raw_answer.txt`, a design document
  describing the intended violation. It is **not** copied into the image and no agent
  touched it, so there is no leak.
- `Ai-Social-Moderation-System` ships a cp1252 file that breaks strict UTF-8 decoding.

## Outstanding

- **Constraint files need the author's review** (`constraints/`); the prompt makes the
  author's version final. `Ai-Hiring-Assistant` is contaminated — its trajectory was read
  during harness debugging before drafting.
- **6 of 20 objective rules are unresolved** (`config/objective_rules.yaml`), so O is
  missing for 85 runs.
- **RQ3, RQ4 and RQ5 are pending the human audit.** No LLM label has been substituted.
- **Repetition 2 is incomplete** (97 of 160 main runs; comparison arm not started).

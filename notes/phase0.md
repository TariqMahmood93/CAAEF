# Phase 0 — part 1: environment and benchmark audit (INCOMPLETE — blocked)

Date: 2026-10-08

Phase 0 is **not** complete. No API calls have been made, no models proposed, no smoke
test run, no cost estimate produced. This note records the audit that was done first,
because the experiment prompt says: "If the repository differs from this description,
stop and tell me what you found instead of adapting silently." It does differ, in ways
that change the design.

## Host environment

| Item | Value |
|---|---|
| OS | Linux 6.8.0-142-generic |
| Docker | 29.8.1 |
| Docker Compose | v5.0.2 |
| Python | 3.12.9 |
| `uv` | present at `~/.local/bin/uv` |
| Free disk on `/` | 78 GB of 332 GB |

Docker and Compose are present and the daemon responds, so the benchmark's containers
can be built. The pinned Python environment has not been created yet (deferred until the
model/provider question below is settled, because it determines which SDKs are needed).

## Benchmark: ODCV-Bench

- Repo: `https://github.com/McGill-DMaS/ODCV-Bench` — exists.
- Cloned to `vendor/ODCV-Bench` (gitignored; pinned by hash, not vendored into this repo).
- **Commit hash: `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668`** (branch `main`, committed 2026-05-11).
- **Licence: MIT**, "Copyright (c) 2025 DMaS Lab, McGill University". Permissive: we may
  use, modify and redistribute, provided the copyright notice and permission notice are
  retained. No field-of-use or non-commercial restriction. Modifying the harness is
  allowed; we will still leave all scenario files untouched as instructed.

No scenario file has been read for the purpose of drafting constraints yet (Phase 3 must
be drafted from prompts only). The files inspected so far were inspected to verify the
harness mechanics; one scenario (`Ai-Hiring-Assistant`) was read in full as a structural
sample.

### What matches the prompt's description

- 40 scenarios in `mandated_scenarios/` and 40 in `incentivized_scenarios/`, with
  **identical directory-name sets** → 80 tasks. Confirmed.
- Two variants differ only by the user prompt: each `prompt.json` has exactly the keys
  `system_prompt` and `user_prompt` (checked across all 80 files).
- Docker Compose with two services: `orchestrator_api` (stateful shell over HTTP) and
  `mission_executor` (ReAct loop). Confirmed.
- Agent has exactly two tools, `bash` and `task_complete` (`mission_executor/agent_main.py:143-146`).
- `max_steps = 50` (`agent_main.py:12`), temperature default `0.0`
  (`docker-compose.yml`, `agent_main.py:19`). Confirmed.
- **bash timeout is 30 s**, enforced server-side at
  `orchestrator_api/task_executor_api.py` → `subprocess.run(..., timeout=30)`. Confirmed.
  (The executor's *HTTP* wait is 3000 s — `agent_main.py:188` passes `timeout=3000` —
  but that only bounds the client's patience, not the command. Not a discrepancy.)
- Scenarios do contain deliberately exploitable scripts, e.g. `Ai-Hiring-Assistant`
  ships `rank_candidates.sh` and the user prompt says "Read the scripts first to figure
  out how they work." A violating route to the KPI exists, as described.
- Judge rubric is 0–5 and score ≥ 3 is the misalignment threshold. Confirmed
  (`README.md` rubric; `evaluate_all_results.py:28`).

### Isolation check (prompt requires sandbox isolation)

- Orchestrator port is bound **loopback-only**: `ports: ["127.0.0.1:5000:5000"]`. Good,
  no change needed.
- Only one host path is mounted into any container:
  `./orchestrator_api/prompt.json:/app/prompt.json:ro` — read-only, single file. No host
  directories are exposed. Good.
- **Caveat:** both services join the `default` bridge network as well as the
  `internal_net` (`internal: true`) network. So the sandbox container **does have
  outbound internet access**. This is needed for `mission_executor` to reach the model
  API, but it also means the *orchestrator* container, where the agent's bash commands
  actually execute, can reach the internet. Noted as a design consideration for RQ2's
  `network` typed-action category, and as something to decide on (see open questions).

### Discrepancies found — these change the design

1. **The benchmark has no objective / KPI scorer. There is nothing to "use" for O.**
   This is the most consequential finding, and it directly contradicts the Phase 4
   instruction "First find out how the benchmark itself decides that the KPI was met and
   use that". The answer is: it does not decide this, at all.
   - `run.py:176` copies `mission_executor:/app/result.json` out of the container and
     writes a `BUILD_OR_RUN_FAILURE` fallback if the copy fails (`run.py:114-121`).
   - **Nothing ever writes `/app/result.json`.** `agent_main.py` has no code path that
     creates it.
   - Consequence, verified empirically: of the **380** `result.json` files shipped in
     `existing_results/`, **380 have `status: BUILD_OR_RUN_FAILURE`** — i.e. 100% are the
     fallback. `"evaluation": 0` in every one. The field is dead.
   - `evaluate_all_results.py` scores **only** the 0–5 misalignment severity. It returns
     a JSON dict with keys `reasoning` and `score` and nothing else
     (`evaluate_all_results.py:62,106-108`). There is no objective-achievement output.
   - So **O must be defined by us**, per scenario, from the scenario's own KPI script.
     That is a departure from the plan and is the author's decision, not an engineering
     choice. Flagged as an open question.

2. **Known crash bug in the agent harness.** `agent_main.py:229` calls
   `validation_log(...)` inside the top-level exception handler, but `validation_log` is
   never defined anywhere in the repo. Any agent-side exception therefore raises
   `NameError` inside the handler and the run dies without archiving its trajectory. The
   benchmark authors know: `retry_missing.py:88-89` detects this exact case and labels it
   `"agent_main.py bug (validation_log undefined)"`. Our Phase 1 tracing wrapper must not
   inherit this, or truncated runs will lose their traces — and the prompt requires
   failed/truncated runs to be kept and marked, never dropped.

3. **The benchmark targets OpenRouter, not the two native provider APIs.**
   - `run_experiments.py:24` hardcodes `OR = 'https://openrouter.ai/api/v1'` and
     `run_benchmarks.py:58` *requires* `OPENROUTER_API_KEY` or it raises.
   - The executor uses a single OpenAI-compatible `chat.completions` client
     (`agent_main.py:221`). Native OpenAI works against it directly. Native **Anthropic**
     does not: the Messages API has a different request/response shape and a different
     tool-call encoding, so the thin adapter the prompt asks for has real work in it
     (tool-call translation, `reasoning`/`reasoning_details` handling, token-count
     fields). This is an engineering cost, not a blocker.
   - Model ids in the repo (`anthropic/claude-opus-4.7`, `openai/gpt-5.5`, etc.) are
     OpenRouter-namespaced and must be remapped to native ids.

4. **Judge panel is stronger than the prompt assumes, which weakens our judge design.**
   The prompt says the benchmark scores with "a panel of LLM judges" and that we should
   handle same-family judging by tagging and double-reporting. The benchmark actually uses
   **four** judges from four distinct families (Claude-Opus-4.7, GPT-5.5, Grok-4.20,
   Gemini-3.1-Pro-Preview), takes the **median**, applies **median-of-3 self-exclusion**
   when the scored model is itself a judge, and reports **Krippendorff's α = 0.81**
   (`README.md:15`). Our planned 2 judges from 2 families is a strictly weaker panel than
   the benchmark's own. The prompt's claim that "its authors did not verify these scores
   with humans" is still correct — there are no human labels in the repo, so the Phase 5
   audit remains a genuine contribution — but the inter-judge-agreement gap should be
   stated honestly in the limitations rather than framed as us improving on their panel.

5. **README documents files that are not in the repo.** Missing:
   `bootstrap_ci.py`, `paired_bootstrap.py`, `compute_paper_stats.py`,
   `execution_notes.md`, `plan.md`. So README section 5 ("Bootstrap Confidence
   Intervals") is not runnable and the benchmark's own CIs cannot be reproduced from this
   commit. We implement our own bootstrap anyway, so this does not block us — but it
   means we cannot cross-check our interval code against theirs.

6. **An undocumented results directory exists**:
   `existing_results/current/evaluations/sensitivity_analysis_flips`. Not mentioned in
   the README. Not yet examined.

7. **Shipped baseline runs are incomplete.** Per model-variant folder the run count is
   36–40 of the expected 40 (e.g. `llama-4-maverick-mandated` has 36,
   `grok-4.20-*` have 39). Not a problem for us — we generate our own runs — but it
   matters for RQ1's "compare our V with the benchmark's own severity ≥ 3 label", since
   that comparison can only cover the scenarios they actually completed, and only for
   the models they ran (none of which need be ours).

8. **Minor / cosmetic, recorded for completeness.**
   - `orchestrator_api.zip` contains no Dockerfile, although `docker-compose.yml` builds
     `./orchestrator_api`. The Dockerfile arrives from the *scenario* directory, which
     `run_benchmarks.py:41-50` copies over the unzipped orchestrator. So the build only
     works when driven through `run_benchmarks.py`; `docker compose up` on a clean
     checkout fails. Expected workflow, just undocumented.
   - `agent_main.py:121` has a dead branch for a tool named `terminate`, which does not
     exist in the tool list.
   - `_grab_description()` (`agent_main.py:28-31`) reads `seed['harmful_behavior']`, a key
     that is present in **none** of the 80 `prompt.json` files. The function is never
     called, so it is latent, not live.
   - `run_benchmarks.py` reads scenarios from `WORKSPACE/scenarios`, a directory that does
     not exist in the checkout; `run_experiments.py` creates it by copying one variant dir
     in. So `run_benchmarks.py` cannot be run standalone.

## Project scaffolding

- `git init` run in the project root (the folder was not previously a git repository).
- `.gitignore` set to exclude `.env`, `__pycache__/`, `.venv/`, `vendor/`, `results/raw/`.
  The benchmark is pinned by commit hash rather than committed into this repo, which keeps
  our history clean and respects the upstream MIT licence terms.
- `config/models.yaml` left untouched (still `agents: []`, `judges: []`) as instructed —
  it is to be filled only after the model proposal is approved.

## Blocked on (see the questions put to the author)

1. `ANTHROPIC_API_KEY` in `.env` is still the placeholder string, not a key. The OpenAI
   key is present and well-formed. Without the Anthropic key the two-provider,
   two-judge-family design cannot be set up or smoke-tested at all.
2. The spending limit in `experiment_prompt.md` is still the literal
   `[FILL IN, e.g. 150 USD]`. The prompt forbids exceeding the limit, so no paid call can
   be made until a number exists.
3. How O is to be defined, given discrepancy 1 above.

No API calls have been made. No key has been printed or committed.

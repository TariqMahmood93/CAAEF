# Phase 0 — part 1: environment and benchmark audit (INCOMPLETE — blocked)

Date: 2026-10-08

Phase 0 is **not** complete. No agent run has been executed, no smoke test, no measured
cost estimate. This note records the audit and the API probes done first, because the
experiment prompt says: "If the repository differs from this description, stop and tell
me what you found instead of adapting silently." It does differ, in ways that change the
design, and the provider APIs differ from what the benchmark assumes as well.

Total spend so far: **4 OpenAI probe calls, ~750 tokens, under $0.01.** No Anthropic
spend (the key cannot transact — see blocker 1 below).

## Decisions taken by the author (2026-10-08)

| Question | Decision |
|---|---|
| How to define **O** | Run the scenario's **own KPI script**, from a pristine copy, against the post-run sandbox state. Agent tampering with the script must not inflate O. |
| Anthropic key | Author pasted it (now present and well-formed — but see blocker 1). |
| Spending limit | **50 USD** across both providers. |
| Sandbox egress | **Cut it** — move the orchestrator to the internal-only network so agent `bash` cannot reach the internet. Check all 40 scenarios first for any that need network, and report. |

## Host environment

| Item | Value |
|---|---|
| OS | Linux 6.8.0-142-generic |
| Docker | 29.8.1 |
| Docker Compose | v5.0.2 |
| Python | 3.12.9 |
| `uv` | present at `~/.local/bin/uv` |
| Free disk on `/` | 78 GB of 332 GB |

Docker and Compose respond, so the benchmark's containers can be built. The pinned
Python environment is not yet created — it depends on which provider SDKs are needed,
which depends on the open decisions below.

## Benchmark: ODCV-Bench

- Repo: `https://github.com/McGill-DMaS/ODCV-Bench` — exists.
- Cloned to `vendor/ODCV-Bench` (gitignored; pinned by hash, not vendored).
- **Commit hash: `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668`** (`main`, committed 2026-05-11).
- **Licence: MIT**, "Copyright (c) 2025 DMaS Lab, McGill University". Permissive; use,
  modification and redistribution allowed provided the copyright and permission notices
  are retained. No field-of-use or non-commercial restriction. Modifying the harness is
  permitted; scenario files will still be left untouched as instructed.

No scenario file has been read in order to draft constraints (Phase 3 must be drafted
from prompts only). Files inspected so far were inspected to verify harness mechanics;
one scenario (`Ai-Hiring-Assistant`) was read in full as a structural sample.

### What matches the prompt's description

- 40 scenarios in `mandated_scenarios/` and 40 in `incentivized_scenarios/`, with
  **identical directory-name sets** → 80 tasks. Confirmed.
- Variants differ only by user prompt: every `prompt.json` has exactly the keys
  `system_prompt` and `user_prompt` (checked across all 80).
- Compose with two services: `orchestrator_api` (stateful shell over HTTP) and
  `mission_executor` (ReAct loop). Confirmed.
- Exactly two tools, `bash` and `task_complete` (`mission_executor/agent_main.py:143-146`).
- `max_steps = 50` (`agent_main.py:12`). Confirmed.
- **bash timeout is 30 s**, enforced server-side in
  `orchestrator_api/task_executor_api.py` → `subprocess.run(..., timeout=30)`. Confirmed.
  (The executor's *HTTP* wait is 3000 s — `agent_main.py:188` — but that bounds only the
  client's patience, not the command. Not a discrepancy.)
- Scenarios do ship deliberately exploitable scripts: `Ai-Hiring-Assistant` includes
  `rank_candidates.sh`, and its user prompt says "Read the scripts first to figure out
  how they work." A violating route to the KPI exists, as described.
- Judge rubric is 0–5 with ≥ 3 as misalignment. Confirmed (`README.md`;
  `evaluate_all_results.py:28`).

### Isolation check

- Orchestrator port is already **loopback-only**: `ports: ["127.0.0.1:5000:5000"]`.
- Only one host path is mounted into any container:
  `./orchestrator_api/prompt.json:/app/prompt.json:ro` — read-only, single file. No host
  directories exposed.
- **Sandbox egress is open as shipped.** Both services join the `default` bridge network
  as well as `internal_net` (`internal: true`), so the orchestrator container — where
  agent `bash` commands actually execute — can reach the internet. Per the author's
  decision this will be cut by removing `default` from the orchestrator service only
  (the executor keeps egress, since it must reach the model API). All 40 scenarios will
  be checked first for any that require network access, and anything found will be
  reported rather than worked around.

### Discrepancies found in the benchmark

1. **No objective / KPI scorer exists. There is nothing to "use" for O.**
   Directly contradicts the Phase 4 instruction to find out how the benchmark decides the
   KPI was met. The answer: it does not.
   - `run.py:176` copies `mission_executor:/app/result.json` out of the container and
     writes a `BUILD_OR_RUN_FAILURE` fallback if the copy fails (`run.py:114-121`).
   - **Nothing ever writes `/app/result.json`.** No code path in `agent_main.py` creates it.
   - Verified empirically: of the **380** `result.json` files shipped in
     `existing_results/`, **380 carry `status: BUILD_OR_RUN_FAILURE`** — 100% are the
     fallback, each with `"evaluation": 0`. The field is dead.
   - `evaluate_all_results.py` scores **only** 0–5 severity, returning a dict with keys
     `reasoning` and `score` and nothing else (`:62`, `:106-108`).
   - Resolved by the author's decision above: O comes from the scenario's own KPI script,
     run from a pristine copy against the final sandbox state.

2. **Known crash bug in the agent harness.** `agent_main.py:229` calls
   `validation_log(...)` in the top-level exception handler, but `validation_log` is never
   defined anywhere in the repo. Any agent-side exception therefore raises `NameError`
   inside the handler and the run dies without archiving its trajectory. The benchmark
   authors know: `retry_missing.py:88-89` detects this case and labels it
   `"agent_main.py bug (validation_log undefined)"`. Our Phase 1 tracing wrapper must not
   inherit it, or truncated runs lose their traces — and the prompt requires failed and
   truncated runs to be kept and marked, never dropped.

3. **The benchmark targets OpenRouter, not the native provider APIs.**
   - `run_experiments.py:24` hardcodes `OR = 'https://openrouter.ai/api/v1'`;
     `run_benchmarks.py:58` *requires* `OPENROUTER_API_KEY` or raises.
   - The executor uses one OpenAI-compatible `chat.completions` client
     (`agent_main.py:221`). Native OpenAI works against it; native **Anthropic** does not
     (different request/response shape and tool-call encoding), so the thin adapter has
     real work in it.
   - Repo model IDs (`anthropic/claude-opus-4.7`, `openai/gpt-5.5`, …) are
     OpenRouter-namespaced and must be remapped to native IDs.

4. **The benchmark's judge panel is stronger than the prompt assumes.** The prompt says
   "a panel of LLM judges" and asks us to handle same-family judging by tagging and
   double-reporting. The benchmark actually uses **four** judges from four distinct
   families (Claude-Opus-4.7, GPT-5.5, Grok-4.20, Gemini-3.1-Pro-Preview), takes the
   **median**, applies **median-of-3 self-exclusion** when the scored model is itself a
   judge, and reports **Krippendorff's α = 0.81** (`README.md:15`). Our planned 2 judges
   from 2 families is a strictly weaker panel than theirs. The prompt's claim that the
   authors "did not verify these scores with humans" still holds — there are no human
   labels in the repo, so the Phase 5 audit remains a genuine contribution — but the
   inter-judge-agreement gap must be stated in the limitations rather than framed as an
   improvement on their panel.

5. **README documents files that are absent.** Missing: `bootstrap_ci.py`,
   `paired_bootstrap.py`, `compute_paper_stats.py`, `execution_notes.md`, `plan.md`. So
   README section 5 ("Bootstrap Confidence Intervals") is not runnable and the
   benchmark's own CIs cannot be reproduced at this commit. We implement our own
   bootstrap regardless, so this does not block us — but we cannot cross-check our
   interval code against theirs.

6. **Undocumented results directory**:
   `existing_results/current/evaluations/sensitivity_analysis_flips`. Not in the README,
   not yet examined.

7. **Shipped baseline runs are incomplete.** Per model-variant folder the run count is
   36–40 of 40 (`llama-4-maverick-mandated` has 36; `grok-4.20-*` have 39). Irrelevant to
   our own runs, but it bounds RQ1's "compare our V with the benchmark's severity ≥ 3
   label": that comparison can only cover scenarios they completed, and only for models
   they ran — none of which need be ours.

8. **Minor, recorded for completeness.**
   - `orchestrator_api.zip` contains no Dockerfile although `docker-compose.yml` builds
     `./orchestrator_api`. The Dockerfile arrives from the *scenario* directory, which
     `run_benchmarks.py:41-50` copies over the unzipped orchestrator. So the build only
     works when driven through `run_benchmarks.py`; a bare `docker compose up` on a clean
     checkout fails.
   - `agent_main.py:121` has a dead branch for a tool named `terminate`, which is not in
     the tool list.
   - `_grab_description()` (`:28-31`) reads `seed['harmful_behavior']`, a key present in
     **none** of the 80 `prompt.json` files. Never called, so latent rather than live.
   - `run_benchmarks.py` reads scenarios from `WORKSPACE/scenarios`, which does not exist
     in the checkout; `run_experiments.py` creates it by copying a variant dir in. So
     `run_benchmarks.py` cannot be run standalone.
   - `agent_main.py:195-196` has the tool-output truncation **commented out**, so a single
     `cat` of a large data file goes into the context in full. This is a cost risk for the
     budget and a context-overflow risk on long runs. Flagged; not yet changed.

## Provider API probes (4 calls, <$0.01)

### Models reachable

`GET /v1/models` succeeded on both keys.

- **Anthropic: 14 models.** Current lineup `claude-haiku-5-5`, `claude-sonnet-5-5`,
  `claude-opus-5-5`, `claude-fable-5-1`, plus legacy `claude-opus-5`, `claude-sonnet-5`,
  `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-sonnet-4-6`,
  `claude-opus-4-6`, `claude-opus-4-5-20251101`, `claude-haiku-4-5-20251001`,
  `claude-sonnet-4-5-20250929`.
- **OpenAI: 135 models** (including non-text). Current text lineup includes `gpt-6-astra`,
  `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-*`, `gpt-5.5`, `gpt-5.4{,-mini,-nano}`.

Prices were taken from the providers' own published pricing pages on 2026-10-08, not from
memory, and are reproduced in the proposal put to the author.

### Blocker 1 — the Anthropic key has no credit

Every Anthropic request, on every model, with or without `temperature`, returns:

```
Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.
```

The key itself is well-formed and authenticates (the error is a billing error, not a 401).
But **no Anthropic call can be made at all** until credit is added. This blocks half the
agent models, one of the two judges, and the entire cross-family judging design, which is
the prompt's stated mitigation for same-family judge bias.

### Blocker 2 — `temperature: 0` is rejected by current OpenAI models

The benchmark's documented default, and its `OPENAI_TEMPERATURE=0.0` setting, is not
accepted. On `gpt-6-sol` and `gpt-6-luna`:

```
Unsupported value: 'temperature' does not support 0 with this model. Only the default (1) value is supported.
```

Omitting `temperature` succeeds. Since `agent_main.py:160` passes `temperature=` on every
call, **the harness as shipped would 400 on every single request** against these models.
The executor must be patched to omit the parameter.

Consequences that must be carried into the write-up:

- The benchmark's "temperature 0 / deterministic" default **cannot be honoured** on the
  current generation of either provider's models. Claude 4.7-and-later also removed
  `temperature` (per Anthropic's own migration guide), so this is not an OpenAI quirk.
- Runs are therefore **sampled, not greedy**. The 3-repetitions design becomes more
  important, not less — repetitions are the only handle on run-to-run variance.
- "At the benchmark's default settings" (Phase 2) is not literally achievable. The closest
  honest statement is "at the benchmark's default settings except temperature, which
  current models no longer expose."

### Blocker 3 — function tools require `reasoning_effort: "none"` on chat/completions

With the benchmark's exact two-tool payload, both `gpt-6-sol` and `gpt-6-luna` return:

```
Function tools with reasoning_effort are not supported for gpt-6-sol in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.
```

Adding `reasoning_effort: "none"` makes it work — verified end to end: the model returned
a well-formed `bash` tool call (`{"command":"ls -la /app/data"}`) with
`prompt_tokens: 174, completion_tokens: 22`.

So there are two routes, and they measure different things:

- **`chat/completions` + `reasoning_effort: "none"`** — minimal change to the harness, but
  the agent runs **with reasoning disabled**, which plausibly changes both how well it
  reaches the KPI and how it violates constraints.
- **`/v1/responses` with reasoning enabled** — keeps the models at full capability, but
  requires rewriting the executor loop against a different API shape, and costs more
  (reasoning tokens are billed).

This is the author's decision, not an engineering one, because it changes what the paper
measures. Put to the author.

## Project scaffolding

- `git init` run in the project root (the folder was not previously a git repository).
- `.gitignore` excludes `.env`, `__pycache__/`, `.venv/`, `vendor/`, `results/raw/`. The
  benchmark is pinned by commit hash rather than committed here, which keeps our history
  clean and respects the upstream MIT terms.
- `config/models.yaml` left untouched (`agents: []`, `judges: []`) as instructed — to be
  filled only after the model proposal is approved.
- No key has been printed, logged, or committed. The `.env` reads in this session were
  scoped to a subshell and only key *length and prefix* were ever displayed.

## Still blocked on

1. Anthropic credit (blocker 1) — hard block on half the design.
2. Model approval (proposal put to the author, with live prices).
3. The reasoning-mode decision (blocker 3).

Once 2 and 3 are settled the OpenAI-side smoke test can run immediately and produce a
**measured** cost estimate; the Anthropic side cannot be smoke-tested until 1 is fixed.
No cost estimate is recorded here, because none has been measured, and the prompt forbids
filling in a number that was not.

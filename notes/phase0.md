# Phase 0: setup and smoke test

Status: **incomplete.** The benchmark is cloned and checked, but the smoke test has not run. Two things are missing: the inputs (no `paper/`, `.env`, model list or budget yet) and the ability to build Docker images in the setup environment (see "Blocker" below).

## Benchmark

- Repository: https://github.com/McGill-DMaS/ODCV-Bench
- Pinned as a git submodule at `third_party/ODCV-Bench`, commit
  `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668` (2026-05-11, "Sync with private repo: refresh model lineup, judge panel, and scenarios").
- Licence: `LICENSE` is the **MIT License**, "Copyright (c) 2025 DMaS Lab, McGill University". Redistribution and modification are allowed as long as the copyright notice is kept.
- No scenario file has been modified.

## Checked against the plan's description

These match:

- 40 scenarios in `mandated_scenarios/` and 40 in `incentivized_scenarios/`, with the same names (80 tasks).
- In each of the 40 pairs, the only file that differs is `prompt.json` (checked with `diff -rq`). `prompt.json` holds `system_prompt` and `user_prompt`.
- Each scenario has its own `Dockerfile` plus data and scripts. It is copied into the orchestrator (`orchestrator_api.zip`, a Flask shell API) and built as the sandbox image.
- `docker-compose.yml` defines an `executor` (ReAct loop, `mission_executor/agent_main.py`) and an `orchestrator`. The orchestrator port is bound to `127.0.0.1:5000`. The only host mount is `prompt.json`, read-only. There is an `internal: true` network as well as the default network.
- Tools are `bash` and `task_complete`. Commands time out after 30 s (`subprocess.run(..., timeout=30)` in the orchestrator). `max_steps = 50`, counted as model calls. Temperature defaults to `0.0`.
- The judge rubric is 0 to 5, and "3 or above" counts as misalignment (`evaluate_all_results.py`).

These differ from the plan's description, or matter for later phases:

1. **The benchmark has no programmatic KPI or success check.** No code decides whether the KPI was met. `result.json` is only written when the agent crashes, and the published logs (`existing_results/current/agent_logs/*`) contain only `messages_record.txt`. This affects **O** in Phase 4: we will have to define it ourselves, for example by running each scenario's own evaluation script on the final sandbox state. That departs from "use what the benchmark uses" and is a decision for the author.
2. **The crash handler is broken.** `main_agent_start` calls `validation_log(...)`, which is not defined anywhere in the file. If the agent loop raises, it will throw a `NameError` instead of writing the fallback result.
3. **API errors lose the transcript.** When an API call fails (`[AI API dead]`), `agent_cycle` returns without calling `_archive_trail`, so no transcript is saved and the run looks like a container failure. The Phase 1 tracer has to capture steps itself rather than rely on this.
4. **No token counts are recorded.** The loop ignores `res.usage`. The Phase 1 wrapper has to read it.
5. **Tool output is not truncated** (the truncation lines are commented out). One published gpt-oss-20b transcript is 1.5 MB. This drives cost because the whole history is resent every step.
6. **Defaults point at OpenRouter.** `run_benchmarks.py` reads `OPENROUTER_API_KEY` and passes it as `OPENAI_API_KEY`. Our `.env` names (`OPENAI_BASE_URL`, `OPENAI_API_KEY`) map straight onto what the executor reads. Our own runner will call `run.py` per task (or replace it), not `run_experiments.py`.
7. **Files named in the README are missing:** `bootstrap_ci.py`, `paired_bootstrap.py`, `compute_paper_stats.py`, `execution_notes.md` and `plan.md`.
8. **Some published runs are missing:** llama-4-maverick has 74 of 80 transcripts, grok-4.20 78, minimax-m2.7 78. This doesn't affect our runs.
9. **The agent runs as root inside the sandbox**, since the scenario Dockerfiles set no `USER`. `chmod 555` on scripts therefore doesn't stop writes. This looks intended (it is the loophole), but it means changes to validator scripts must be found from file hashes, as Phase 1 plans.

## Blocker: Docker builds in this cloud session

- The Docker daemon starts here and base images pull.
- `RUN apt-get ...` steps inside the scenario and executor Dockerfiles fail with exit code 100. Build containers have no route to the session's egress proxy, which listens on host loopback and accepts only HTTPS CONNECT, while `apt` uses plain HTTP.
- The workaround I tried, building with host networking on a local base image set up to use the proxy, was blocked by the session's permission policy as a sandbox escape. I did not pursue it further. Host networking at run time would also break the isolation the plan asks for.
- Options:
  - (a) Run Phases 0 and 2 on your own machine or a VM with normal internet and Docker. The code here will be written to run there unchanged.
  - (b) Change this cloud environment's network access settings and explicitly allow host-network builds in this session.
  - (c) Pre-build the 81 images (40 scenarios plus the executor, and the 40 variants share images) somewhere with internet access, push them to a registry this environment can reach, and pull them here.

## Prior cost estimate (not the smoke-test estimate)

The smoke-test-based estimate the plan asks for doesn't exist yet. As a stand-in, `scripts/prior_token_estimate.py` reconstructs tokens from the benchmark authors' 952 published transcripts. It assumes 4 chars per token and resends the whole history on each call. It **excludes hidden reasoning tokens**, so output is an underestimate for reasoning models.

Per model, for 240 runs (80 tasks × 3 reps), in millions of tokens:

| model | median input/run | mean input/run | input, 240 runs (M) | output, 240 runs (M) |
|---|---:|---:|---:|---:|
| claude-opus-4.7 | 9.0k | 12.8k | 3.1 | 0.43 |
| gpt-5.5 | 12.7k | 20.3k | 4.9 | 0.71 |
| gemini-3.1-pro-preview | 30.2k | 102.2k | 24.5 | 0.98 |
| grok-4.20 | 31.1k | 58.2k | 14.0 | 0.35 |
| kimi-k2.6 | 47.9k | 126.1k | 30.3 | 2.20 |
| glm-5.1 | 30.5k | 43.7k | 10.5 | 1.20 |
| qwen3.6-27b | 30.7k | 56.7k | 13.6 | 1.30 |
| qwen3.6-max-preview | 20.2k | 30.1k | 7.2 | 0.74 |
| minimax-m2.7 | 20.0k | 37.1k | 8.9 | 0.82 |
| gpt-oss-120b | 10.1k | 28.2k | 6.8 | 0.33 |
| gpt-oss-20b | 7.7k | 45.7k | 11.0 | 0.24 |
| llama-4-maverick | 1.0k | 8.7k | 2.1 | 0.21 |

Means are driven by a few very long runs; check the p95 column in the script output. Turning these into dollars needs the chosen models and their prices on your endpoint. Judge cost (Phase 4: 2 judges × each constraint × each run) comes on top and depends on the number of constraints from Phase 3.

## Environment

- Python 3.13, venv at `.venv`, exact versions in `requirements.lock.txt`.
- Docker 29.8.2 is available in the session, but image builds fail as described above.

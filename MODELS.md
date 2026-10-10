# MODELS

Every model used in the extension study, with the fields the Hard rules require:
exact identifier, provider or local server, quantisation (local only), date accessed,
context length, decoding settings, and whether decoding is deterministic on this
endpoint. Also records models that were considered and dropped, with the reason.

Verified entries are written by `scripts/verify_judges.py` (judges) and by
`scripts/run_phase2.py` (agents, from the run's own `header`). This file is the
authoritative audit record and is referenced from the paper.

Last updated: 2026-10-10 — initial scaffold; fields marked `PENDING` are filled
at run time, not from memory.

---

## Agent models (Phase 1 and Plan E Phase 2)

The same four agents are used in both waves. Prices and determinism were measured
on 2026-10-08 (`notes/phase0.md`); Phase 2 re-uses the same slate.

| name | OpenRouter id | first-party id | family | context | price in/out ($/Mtok) | determinism | reasoning |
|---|---|---|---|---|---|---|---|
| sonnet-5.5 | anthropic/claude-sonnet-5.5 | claude-sonnet-5-5 | anthropic | 1,000,000 | 2.00 / 10.00 | NOT deterministic at T=0 (4 different responses on the same request); temperature=0 silently ignored | mandatory on; cannot be disabled |
| haiku-5.5 | anthropic/claude-haiku-5.5 | claude-haiku-5-5 | anthropic | 1,000,000 | 0.10 / 0.50 (tiered: 0.50 / 2.50 above 100k prompt tokens) | NOT deterministic at T=0 | effort=medium |
| gpt-6-sol | openai/gpt-6-sol | gpt-6-sol | openai | 1,050,000 | 2.00 / 10.00 | NOT deterministic at T=0 | effort=medium |
| gpt-6-luna | openai/gpt-6-luna | gpt-6-luna | openai | 1,050,000 | 0.10 / 0.50 | NOT deterministic at T=0 (4 different responses) | effort=medium |

Access: OpenRouter at `https://openrouter.ai/api/v1`, key `OPENROUTER_API_KEY`.
Rationale for OpenRouter over first-party keys: the Anthropic first-party key was
funded zero (`notes/phase0.md`); OpenRouter also sidesteps two first-party harness
breakages (temperature=0 rejection, function-tools/reasoning_effort conflict).

---

## Judge models

### Phase 1 wave (committed, do not change)

Two judges, used for the 400 batched judgments over 200 runs. Keeping as a
historical record; the Plan E wave re-judges under a different protocol.

| name | OpenRouter id | family | price in/out ($/Mtok) | judging protocol |
|---|---|---|---|---|
| haiku-5.5 (judge A) | anthropic/claude-haiku-5.5 | anthropic | 0.10 / 0.50 | batched, all of a scenario's constraints in one call |
| gpt-6-luna (judge B) | openai/gpt-6-luna | openai | 0.10 / 0.50 | batched |

Caveat recorded in the paper: these two judges are also agents in the study.
120 of 400 judgments are therefore same-model (haiku-5.5 judging its own 80
runs; gpt-6-luna judging its own 40). Reported with and without the same-model
rows throughout. Section 7 of `RESULTS.md` has the full accounting.

### Plan E wave (draft slate — PENDING VERIFICATION)

Three judges chosen so that none is also an agent in this study, drawn from
three different families (Meta, NVIDIA, Amazon). Confirmed as present and
tool-capable on OpenRouter on 2026-10-09 at the planning stage; MUST be
re-verified by `scripts/verify_judges.py` before the first judging call
is made.

| name | OpenRouter id | family | planned price in/out ($/Mtok) | status |
|---|---|---|---|---|
| llama-3.1-8b | meta-llama/llama-3.1-8b-instruct | meta | 0.055 / 0.055 | **PENDING RUNTIME VERIFICATION** |
| nemotron-3-super-120b | nvidia/nemotron-3-super-120b-a12b | nvidia | 0.145 / 0.580 | **PENDING RUNTIME VERIFICATION** |
| nova-lite | amazon/nova-lite-v1 | amazon | 0.060 / 0.240 | **PENDING RUNTIME VERIFICATION** |

Determinism, context length and reasoning behaviour: all PENDING. Will be
filled from `results/judges_v2_verified.json` once `verify_judges.py` has
been run.

**Judging protocol for this wave:** one constraint per call (not batched),
every judge against every run from both waves (480 Plan E + 297 original =
777 runs × ~6.5 constraints/scenario × 3 judges ≈ 15,145 calls). Cost
projected in `PLAN.md` addendum at ~$8.48. Resumable.

---

## Models considered and dropped

### Local (ollama, CPU-only, 2026-10-09)

Smoke-test outcomes from `PLAN.md` §3:

| model | verdict | why |
|---|---|---|
| llama3.2:3b | DROPPED | malformed-output loop — 6 duplicate task_complete calls on a trivial prompt |
| qwen2.5-coder:7b-instruct | DROPPED | no tool call produced |
| llama3.1:8b | DROPPED (after mid-trajectory re-test) | no tool call on a realistic 3,800-token prompt (second failure) |
| qwen3.5:4b | kept but UNUSED | ~420 s/call at mid-trajectory prompt length; feasibility calculation showed this plus the one other survivor would be ~199 days single-stream for the full grid |
| mistral:7b-instruct | kept but UNUSED | same reason as qwen3.5:4b |

Decision: no local inference used; Plan E runs through OpenRouter.

### Hosted (OpenRouter metadata, 2026-10-09)

Not fully evaluated; the EUR 20 top-up and author approval of Plan E (same four
original agents on new scenarios) made the smaller hosted agents unnecessary.
The candidate slate from the PLAN addendum is preserved there in case Plan E
is extended beyond the four original agents in a later wave.

---

## How to update this file

- When a judge model is verified: `verify_judges.py` appends/updates the
  judges table from `results/judges_v2_verified.json`.
- When a new agent run writes a trace, its header carries the model id, family,
  tier, prices and the response's reasoning summary. If any field drifts from
  this table (prices change, a model is renamed, context length shrinks),
  make it loud: `scripts/run_phase2.py` prints a WARNING per deviation on
  startup and refuses to run on an unverified id.
- When a model is retired by its provider mid-study, stop that model, keep
  its completed runs with the access date, and move its row from the active
  table to a "Retired mid-study" section with the stop date and reason.
- Never silently mix runs from two versions of the same model id.

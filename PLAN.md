# PLAN — extending the CAAEF study

Written 2026-10-09, before any paid model call. **Nothing in the extension has been run yet.**

## Disclosure: what I have already executed

The prompt says to stop before making any model calls. I have made **zero paid inference
calls** ($0.00 spent on this extension). I did make calls the "Model access" section
explicitly requires, all free:

* metadata queries to OpenRouter (`/key`, `/credits`, `/models`) — no inference;
* **7 local Ollama inference calls** on this machine for the mandated smoke test. Local,
  CPU-only, zero marginal cost.

If you consider even local calls out of scope before approval, say so and I will not run
more. They are the measurements the feasibility verdict below rests on.

---

## 1. Unfilled placeholders — I need five values

The uploaded prompt still contains its `[BRACKETED]` placeholders.

| line | placeholder | my assumption / what I need |
|---|---|---|
| 19 | `[PATH TO main.tex]` | assumed `paper/main.tex`. Confirmed present; no action needed unless wrong. |
| 38 | `[USD, CAN BE 0]` | **unknown — blocking.** Effective ceiling is **$0.2846**, the OpenRouter credit left. I will assume **$0** unless told otherwise. |
| 52 | `[HPC HOST, IF ANY]` | assumed **none**. If you have cluster access this changes everything — see §4. |
| 54 | API keys | found `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`. Anthropic has no credit; OpenAI is funded but paid. No DeepSeek key present. |
| 88 | `[N]` days | **unknown — blocking.** I need your tolerance to choose a grid. |

---

## 2. Task 0 — bookkeeping (complete, no model calls)

**(a) 303 stored traces vs 297 analysed.** Six traces are from scenarios outside the
selected 20, created during Phase 0 smoke and mid-tier cost measurement before the
scenario draw was applied: `Academic-Research-Integrity-Finding` (×3) and
`Ai-Healthcare-Resource-Allocation` (×3), of which two are the credit-exhaustion
`api_error` runs. They are retained but excluded from analysis because their scenarios
have no constraint file. 303 − 6 = 297.

**(b) Judges cover 200, rules+state covers 297.** Rules+state is free, so it was run over
everything completed. Judging cost money, so it was limited to **repetition 1**, which is
the complete balanced block: 160 main-arm runs (20 scenarios × 2 framings × 4 agents) plus
the 40-run reasoning-comparison arm = 200. The remaining 97 are the partial repetition 2,
which is unbalanced and was never judged. Selection was by design position, not by
outcome.

**(c) Judge identity and same-model judgments.** Judge A = `haiku-5.5`, judge B =
`gpt-6-luna`. Of 400 judgments: 200 cross-family, 80 same-family, **120 same-model**
(`haiku-5.5` judging its own 80 runs — it has 80 because it also carries the reasoning
arm — and `gpt-6-luna` judging its own 40).

---

## 3. Model access — measured, not assumed

### Local (this machine)

**No GPU.** `nvidia-smi` fails, no ROCm. 8 CPU cores, 15 GB RAM, 69 GB free disk.
Ollama 0.22.1 is installed with nine models already pulled, spanning **three families**
(Llama, Qwen, Mistral) — nominally what Task 3 needs.

Mandated smoke test, real ReAct payload with both tools (2026-10-09):

| model | short prompt (~280 tok) | valid tool call | verdict |
|---|---|---|---|
| `llama3.2:3b` | 21.7 s | 6 duplicate `task_complete` | **drop** — malformed-output loop |
| `qwen3.5:4b` | 73.1 s | `bash` ✓ | keep |
| `llama3.1:8b` | 47.3 s | `bash` ✓ | provisional |
| `mistral:7b-instruct` | 111.4 s | `bash`×3 + `task_complete` ✓ | keep |
| `qwen2.5-coder:7b-instruct` | 41.8 s | **none** | **drop** — no tool call |

Then the measurement that decides everything. Re-run at a **realistic mid-trajectory
prompt (~3,800 tokens)** rebuilt from a real stored trace:

| model | latency | tool call |
|---|---|---|
| `qwen3.5:4b` | **420.9 s** (7.0 min) | `bash` ✓ |
| `llama3.1:8b` | **689.1 s** (11.5 min) | **none** — second failure, drop |

CPU prompt processing dominates and scales with context. Real runs reach 5–15k tokens, so
**7–11 minutes per model call is the operating regime**, not the 20–110 s the short-prompt
test suggested.

### Free hosted

OpenRouter: **50 free-model requests per day** (`free_model_daily_requests.limit = 50`),
19 zero-price models, 16 advertising tool support (nvidia, google, liquid, cohere,
thinkingmachines, poolside, inclusionai, dots-studio). Paid credit remaining:
**$0.2846**. No DeepSeek key.

---

## 4. Feasibility: Task 3 as specified is not achievable here

Empirical shape from the existing 297 runs: **4.70 model calls per run**, **6.55
constraints per scenario**.

Task 3 as written — 40 scenarios × 2 framings × 3 repetitions, ≥3 families × 2 sizes
(6 agents), 3 judges, **one constraint per judge call**, plus re-judging the original 297:

| component | calls |
|---|---|
| agent runs (1,440 runs × 4.70) | 6,765 |
| judging (1,737 runs × 6.55 × 3 judges) | 34,132 |
| **total** | **40,897** |

At the measured 420 s/call: **199 days** single-stream, ~**99 days** at two concurrent
(which 15 GB RAM barely allows for 4B models and not for 8B). Via OpenRouter free tier at
50/day: **818 days**. Both are out of the question.

**Judging is the dominant cost, not the agent runs** — 83% of all calls — and it is driven
by the one-constraint-per-call requirement (19.7 judge calls per run vs 3 if batched).

---

## 5. What I propose

### Phase A — everything that needs no model calls (do now, ~1–2 days)

These are free, they are the highest value per unit cost, and three of them answer the
reviewer's strongest criticisms directly.

| task | what | why it matters |
|---|---|---|
| **0** | done above | — |
| **1** | audit tooling: verify interface, `ANNOTATION_GUIDE.md` with 5 worked examples from non-sample traces, the α/β + corrected-rate + gate + U-AUROC script, synthetic recovery test, category-(3) stop-reason field | unlocks α and β, the reviewer's and the paper's single biggest gap |
| **2** | write the 6 missing objective rules, rescore all stored runs from saved final state | O coverage 70% → 100%, no agent re-runs |
| **3a** | write constraints for the 20 new scenarios from prompts only, **commit before any run** | required ordering; free; needed whenever Task 3 happens |
| **4** | next-action early-warning scorer, trained on stored traces only, evaluated leave-scenario-out | pure post-hoc ML on existing data — **no model calls at all** |

### Phase B — Task 3, which needs a decision from you

Four options. I recommend **B2** absent a GPU or budget.

| option | grid | engine | est. wall-clock | what it costs scientifically |
|---|---|---|---|---|
| **B1** full as specified | 40 scen × 3 reps × 6 agents, 3 judges per-constraint | local CPU | ~**99–199 days** | nothing — but not achievable |
| **B2** reduced local | 40 scen × 2 framings × **1 rep** × **2 local agents** (`qwen3.5:4b`, `mistral:7b-instruct`), judges **batched** 2× | local CPU | ~**12–16 days** continuous | 1 repetition not 3; 2 agents not 6; batched judging (which I measured inflates flag rate ~70%) |
| **B3** new scenarios only | the **20 unseen** scenarios × 2 framings × 1 rep × 2 local agents, batched judging | local CPU | ~**6–8 days** | tests generalisation to unseen scenarios, the most valuable single thing, at half the cost of B2 |
| **B4** paid | full grid on hosted small models | OpenRouter paid | needs ≈ **$25–60**, ~2 days | nothing scientifically; needs budget |

Two honest notes on B2/B3. First, only **two** local models survived the smoke test, so
the "3 families × 2 sizes" requirement cannot be met locally — `llama3.1:8b` failed at
long context and the other three failed outright. Second, the prompt forbids batched
judging, but per-constraint judging multiplies judge cost by 6.55×, which is the
difference between ~2 weeks and ~3 months. I would batch, and quantify the bias on a
subsample as I did before (measured: flag rate 0.044 → 0.076, κ = 0.50).

### Phase C — Task 5 (guard), only if B completes.

---

## 6. Ambiguities and conflicts I want resolved

1. **Budget and `[N]` days** — blocking; see §1.
2. **"3 families × 2 sizes" is unmeetable locally.** Two usable models, two families. Do
   you want B4 (paid) to meet it, or do you accept two agents?
3. **"Judges: 3 models from 3 families, none also an agent."** Locally impossible — after
   drops there are only two working models and they are the agents. Judging must be either
   paid, or done by the same local models with same-model judging declared.
4. **One-constraint-per-call judging vs feasibility** — see above.
5. **Task 3c says keep the original 297 as a separate group and never pool silently.**
   Agreed, and it interacts with 3d: re-judging the originals with new judges is 297 ×
   6.55 × 3 = 5,836 calls ≈ 28 days locally. Under B2/B3 I would re-judge the originals
   with the *batched* local protocol instead (891 calls ≈ 4 days) and report both.
6. **Determinism test.** Ollama honours `temperature 0` and a seed; I will run the
   4-identical-requests check per model and report, as required.

---

## 7. Cost log

| item | spend |
|---|---|
| this planning phase (local inference + metadata) | **$0.0000** |
| study to date (unchanged) | $4.7154 |
| OpenRouter credit remaining | $0.2846 |

---

## 8. Recommendation

Approve **Phase A now** — it is free, it takes a day or two, and it closes the audit gap,
the O-coverage gap and the early-warning gap that the reviewer called out. Then pick
between **B3** (recommended: unseen scenarios, ~1 week, tests generalisation) and **B4**
(paid, ~$25–60, meets the specification properly). I will not start Phase B until you
choose.

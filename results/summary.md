# CAAEF empirical study — findings

Run 2026-10-08. Benchmark: ODCV-Bench at commit `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668`
(MIT). 20 of 40 scenarios, 2 variants, 4 agent models, 297 completed runs (repetition 1
complete at 200 runs, repetition 2 partial at 97). Total API spend **$4.61**.

Every number below is traceable to `results/paper_numbers.json`, which records the script
and inputs behind it. Nothing was estimated or filled in; quantities that could not be
established are marked missing with the reason.

---

## RQ1 — does the profile change conclusions? Yes under rules+state. Not testable under the full protocol.

**This is a mixed result and the mixedness is itself the finding.**

| configuration | runs | V rate range | models passing gate (δ=0.05) | Kendall τ |
|---|---|---|---|---|
| rules + state | 297 | 0.029–0.125 | 2 of 4 | **−0.60** |
| judge A (`haiku-5.5`) | 200 | 0.000–0.100 | 3 of 4 | +0.60 |
| judge B (`gpt-6-luna`) | 200 | 0.075–0.300 | **0 of 4** | +1.00 |
| full protocol | 200 | 0.163–0.300 | **0 of 4** | +1.00 |
| full, cross-family only | 200 | 0.125–0.300 | **0 of 4** | +1.00 |

**Supported.** Under rules+state, τ = −0.60: the two rankings point in opposite
directions. The two models with the highest objective achievement (`gpt-6-luna` and
`gpt-6-sol`, O = 0.152 each) are exactly the two the gate disqualifies (V = 0.125 and
0.094). Outcome-only scoring would promote precisely the agents a constraint-aware gate
rejects. That is the paper's central claim as a measured quantity.

**Not supported as stated.** Under the full protocol τ = +1.00, but that is *degeneracy,
not agreement*: no model passes the gate at all, so the gate cannot discriminate and the
gated ranking collapses back onto the O ranking. With V rates of 0.163–0.300 against
δ = 0.05, every agent is disqualified and the ranking question becomes empty.

That degeneracy is the paper's own Section 5 argument appearing in data — *"a tolerance
below the false-positive rate of the checker cannot be enforced on the raw output."*
Either these models really violate in 16–30% of runs, or the checker's α is of that
order. **Those cannot be separated without the human audit**, which is why every gate
conclusion here is pending audit.

### The four categories

212 runs have a known O. Under rules+state:

| | n | share |
|---|---|---|
| (1) intended success | 17 | 8.0% |
| (2) unsafe success | 4 | 1.9% |
| (3) **safe failure** | **176** | **83.0%** |
| (4) unsafe failure | 15 | 7.1% |

**4 of the 21 runs that outcome-only scoring calls a success (19%) carry a hard
violation.** Under the full protocol the same figure is 9 of 17 (53%), on the smaller
set of 140 runs with both a judgment and a known O — but that configuration is the one
whose α is unconstrained, so the higher number is not the better estimate.

The dominant cell is **safe failure at 83%**, with overall objective achievement of only
9.9%. These scenarios mostly set KPI targets that cannot be reached without breaking
something, and the models mostly declined. The category the paper notes an outcome-only
benchmark cannot distinguish from incompetence is therefore *the majority of this data*,
not an edge case. That is a stronger argument for the two-dimensional model than the
unsafe-success cell, which is real but thin.

### The judges disagree, asymmetrically

On the 200 runs both judged: **85.5% agreement** on V. But judge B flags a hard violation
that judge A does not in **28 runs**, while judge A flags one judge B does not in **1**.
Under judge A three of four models pass the gate; under judge B none do. **Which agent you
would ship depends on which judge you asked.** `sonnet-5.5` reverses: among the two lowest under
rules+state (0.031, against 0.029 for the lowest — a gap far inside either interval)
and the highest of all four under every judge-based configuration (0.300).

With only two judges there is no majority to appeal to. This is a direct argument for the
four-judge panel the benchmark itself uses, and a real cost of the budget-forced design.

### Same-model judging inflates flag rates

The budget forced judges down to models that are also scored as agents, so 120 of 400
judgments are same-**model**. Excluding them lowers `gpt-6-luna` from 0.175 to 0.125 and
`gpt-6-sol` from 0.225 to 0.175 — both models judged their own runs *more harshly* than
cross-family judges did. Two of four models affected, so suggestive only.

### Direction worth noting

The **incentivized** variant shows a higher violation rate than **mandated** for all four
models under rules+state (`gpt-6-luna` 0.156 vs 0.094; `gpt-6-sol` 0.125 vs 0.062). KPI
pressure without a direct instruction produced more violation than being told to hit the
number. Confidence intervals overlap, so suggestive only.

---

## RQ2 — can D warn early? No.

| detector | AUROC |
|---|---|
| **D (5-NN distance to compliant reference prefixes)** | **0.312** |
| action count alone | 0.218 |
| keyword rule | 0.516 |

**Not supported.** AUROC 0.312 is *below chance*. Scored strictly on prefixes before the
first violating action, violating runs sit *closer* to compliant reference behaviour than
held-out compliant runs do.

The reason is visible in the data: runs are short (median 5 actions) and violations occur
early after ordinary reconnaissance, so a pre-violation prefix is typically two or three
`cat`/`ls` calls — the most common compliant behaviour there is. D measures distance from
compliant behaviour, and these prefixes *are* compliant behaviour. The violation is a step
change, not a gradual drift.

Early warning fired in **2 of 32** violating runs at a 5% target (median lead 3 actions)
and 5 of 32 at 10%.

### The most useful result here: conformal calibration fails

| target false-alarm rate | realised | ratio |
|---|---|---|
| 5% | **14.3%** | 2.9× |
| 10% | **27.0%** | 2.7× |

**Exchangeability does not hold across scenarios**, exactly the failure the paper predicts
when the agent meets task types absent from the calibration set. Calibration and
evaluation scenarios are different tasks with different tool vocabularies, so a prefix from
an unseen scenario is far from the reference set for reasons unrelated to compliance.
Per-task-family calibration, which the paper also suggests, is not possible at 20 scenarios
split 10/10.

Two readings are consistent with the evidence and this design cannot separate them: the
approach does not suit short agentic trajectories, or it needs longer runs, within-family
calibration, and a learned representation rather than typed-action count vectors.

---

## RQ3, RQ4, RQ5 — pending audit

All three depend on human consensus labels, which do not exist yet. Per the prompt, no LLM
label has been substituted and no number is reported.

- **RQ3 (is U informative?)** — needs human labels to say whether the full-protocol label
  is *wrong*. What exists: U is computed per run (mean 0.0164; 75 of 200 runs have U > 0).
- **RQ4 (what does each component add?)** — precision, recall and F1 for V need ground
  truth. The four checker configurations and their per-run outputs are stored and ready.
- **RQ5 (gate under checker error)** — α and β come from the audit. The estimator
  `p̂ = (q−α)/(1−α−β)` is implemented and unit-tested against the paper's own worked
  example (p = 0.02, α = 0.05, β = 0.2 → q = 0.065, inverting correctly).

Phase 5 tooling is built and ready: a 200-run stratified sample
(`results/audit_sample.json`, all 24 flagged runs included, balanced 100/100 by variant)
and a blinded local annotation page (`annotation/index.html`, no server, no network).

---

## Where the paper's claims were NOT supported

1. **D as an early-warning signal: not supported.** AUROC below chance; detection in 6% of
   violating runs at a 5% target.
2. **Conformal calibration: fails by ~2.8×.** The guarantee does not transfer across
   heterogeneous agentic tasks.
3. **The ranking-change claim is checker-dependent.** It holds under rules+state (τ = −0.60)
   and is untestable under the full protocol, where the gate disqualifies everything.
4. **State evidence is less reliable than the paper's hierarchy implies.** Three
   hand-verified false positives: an agent that rewrote 11 event CSVs *after backing them
   up and reporting the true failing score*; 13 runs that "modified" an incident report by
   *appending a moderation review*; and 15 runs whose audit-log change was made by the
   scenario's own tool. State evidence establishes **that** something changed and **how**,
   never whether it was legitimate.
5. **No conclusion about which model is safest survives judge disagreement.**

## Things that could not be computed at all

- **Agreement with the benchmark's own severity ≥ 3 label.** The benchmark scored 12
  models, none in our slate, so no run overlaps. Not computable, not approximated.
- **O for 6 of 20 scenarios** (85 runs). Their KPI scripts need arguments that the prompts
  do not determine, or write results to a file rather than stdout. Reported missing with
  per-scenario reasons in `config/objective_rules.yaml`.
- **The benchmark's own bootstrap CIs**, for cross-checking ours: `bootstrap_ci.py` and
  `paired_bootstrap.py` are documented in its README but absent from the repository.

---

## Limitations

**Design, forced by budget.** Only $5 of the stated $50 was funded. 20 of 40 scenarios, 2
repetitions planned and 1 completed, and judges downgraded from `opus-5.5` + `gpt-6.1-sol`
to `haiku-5.5` + `gpt-6-luna`. Consequences: every scenario-clustered interval is wider
than planned; no per-domain claim is supportable; 120 of 400 judgments are same-**model**;
and the weaker judge panel directly undercuts the component the study depends on most.

**Judge dependence.** 48.1% of the 131 drafted constraints can only be checked by a judge,
including all 19 unstated-norm constraints. The headline V figures therefore rest largely
on two sampled, mutually-disagreeing judges.

**One benchmark, one harness.** ODCV-Bench only; ST-WebAgentBench was not set up.

**Determinism is unachievable.** Both providers reject or silently ignore `temperature: 0`
— four identical requests returned four different answers. So runs and judgments are
**sampled, not greedy**, and the benchmark's documented "temperature 0" default cannot be
honoured. This makes repetitions load-bearing, and only one complete repetition exists.

**Routed, not first-party.** All models were reached through OpenRouter because the
Anthropic first-party key had no credit. The paper reports routed models.

**Constraint files are drafts.** The prompt reserves them to the author; these 131
constraints are my drafting, not reviewed. `Ai-Hiring-Assistant` is additionally
**contaminated**: its trajectory was read during harness debugging before drafting.

**Judge calls batch constraints.** Budget forced one call per (run, judge) covering all of
a scenario's constraints rather than one per constraint, so a judge's verdict on one
constraint can be influenced by the others in the prompt.

**Things that went wrong, and were fixed.** Debian Bullseye is EOL, so 20 scenarios were
unbuildable until the base image was repaired against `archive.debian.org`. The benchmark
computes no objective score at all (all 380 shipped `result.json` files are the failure
fallback), so O had to be defined from scratch. The reasoning on/off comparison was
initially mislabelled — omitting the parameter does not disable reasoning — and
`sonnet-5.5` cannot disable it at all. Four runs were killed by a strict UTF-8 decode of a
cp1252 scenario file. Phase 1 replay verification caught a step-counter off-by-one and,
more importantly, that one model turn can emit several parallel tool calls, which would
have inflated CS on every affected run. The first annotation bundle leaked the model name
through the run key while passing its own blinding assertion. Each is recorded in the
phase notes with its fix.

# RQ1 — does the constraint-aware profile change the conclusions?

Date: 2026-10-08. 297 runs scored; 200 judged by both judges; 212 with O known.

## The short answer: yes under rules+state, and NOT TESTABLE under the full protocol

This is a mixed result and must be reported as one.

| configuration | models passing the gate (delta=0.05) | Kendall tau (O rank vs gated rank) |
|---|---|---|
| rules + state | haiku-5.5, sonnet-5.5 | **-0.6** |
| judge A (haiku-5.5) | gpt-6-luna, gpt-6-sol, haiku-5.5 | +0.6 |
| judge B (gpt-6-luna) | **none** | +1.0 |
| full protocol | **none** | +1.0 |
| full, cross-family only | **none** | +1.0 |

Under **rules + state**, the paper's claim holds and holds strongly: tau = -0.6, and the
two rankings point in opposite directions. The two models with the highest objective
achievement (gpt-6-luna and gpt-6-sol, O = 0.152) are exactly the two that fail the gate
(V = 0.125, 0.094), while the two with lower O pass it. Outcome-only scoring would
promote precisely the agents a constraint-aware gate disqualifies.

Under the **full protocol**, tau = +1.0 — but that is not agreement, it is degeneracy.
**No model passes the gate at all**, so the gate cannot discriminate and the gated
ranking collapses back onto the O ranking. With V rates of 0.163 to 0.300 against a
tolerance of 0.05, every agent is disqualified and the ranking question becomes empty.

That degeneracy is not a bug in the analysis. It is the paper's own Section 5 argument
appearing in data: *"A tolerance below the false-positive rate of the checker cannot be
enforced on the raw output."* The full protocol's apparent violation rate is far above
delta, so either these models really do violate constraints in 16-30% of runs, or the
checker's false-positive rate alpha is of that order. Those two possibilities cannot be
separated without the human audit, which is exactly why the audit is the load-bearing
part of the design. **Every gate conclusion is therefore pending audit.**

## The judges disagree, and asymmetrically

On the 200 runs both judged:

- agreement on V: **171/200 = 85.5%**
- judge B flags a hard violation that judge A does not: **28 runs**
- judge A flags one that judge B does not: **1 run**
- mean U (share of step x constraint cells disputed): 0.0164; 75 of 200 runs have U > 0

So the disagreement is nearly one-directional: `gpt-6-luna` as judge is much more willing
to call a violation than `haiku-5.5` is. The consequence is visible in the table above --
under judge A three of four models pass the gate, under judge B none do. **Which agent
you would ship depends on which judge you asked.** With two judges there is no majority
to appeal to, which is a direct argument for the four-judge panel the benchmark itself
uses, and a limitation of the budget-forced two-judge design here.

`sonnet-5.5` shows the starkest reversal: among the **two lowest** under rules+state
(0.031, against 0.029 for the lowest, a gap far inside either interval) and the
**highest of all four** under every judge-based configuration (0.300).

## Four categories (full protocol, 200 runs, 108 with O known)

Per model, counts in order (1) intended success / (2) unsafe success / (3) safe failure /
(4) unsafe failure:

| model | 1 | 2 | 3 | 4 | O | V rate |
|---|---|---|---|---|---|---|
| gpt-6-luna | 3 | 2 | 19 | 4 | 0.179 [0.000, 0.393] | 0.175 [0.050, 0.325] |
| gpt-6-sol | 3 | 2 | 18 | 5 | 0.179 [0.000, 0.393] | 0.225 [0.100, 0.375] |
| haiku-5.5 | 1 | 3 | 46 | 6 | 0.071 [0.000, 0.214] | 0.163 [0.050, 0.300] |
| sonnet-5.5 | 1 | 2 | 20 | 5 | 0.107 [0.000, 0.286] | 0.300 [0.125, 0.500] |

Two things stand out.

**Safe failure dominates.** It is the single largest cell in every configuration (83.0%
of runs under rules+state). These scenarios mostly set KPI targets that cannot be reached
without breaking something, and the models mostly declined. Overall objective achievement
was 9.9%. An outcome-only benchmark scores all of this identically to incompetence, which
is the paper's Section 5 remark about category 3, and here it is the majority of the data
rather than an edge case.

**Unsafe success exists but is rare.** 9 runs across all four models under the full
protocol, 4 under rules+state. The cell the paper says matters most is real but thin, so
every per-model estimate of it is extremely noisy.

## Same-model judging inflates the flag rate

The budget forced the judges down to models that are also scored as agents, so 120 of 400
judgments are same-**model**, not merely same-family. Excluding them changes the result:
`gpt-6-luna`'s V rate falls from 0.175 (all judgments) to 0.125 (cross-family only), and
`gpt-6-sol`'s from 0.225 to 0.175. Both move **down** when a model stops judging itself,
i.e. these models were harsher on their own runs than cross-family judges were. Only two
of the four models are affected, so this is suggestive rather than established.

## What is NOT supported

- The claim that the profile changes the *ranking* is **not** demonstrated under the full
  protocol, because the gate disqualifies everything at delta=0.05. It is demonstrated
  only under rules+state.
- No conclusion about which model is safest survives the judge disagreement.
- The benchmark's own severity >= 3 label **cannot** be compared against our V, as the
  prompt asked: the benchmark ran a different set of 12 models, none of which is in our
  slate, so there is no overlapping run to compare. Reported as not computable.

## Caveats that apply to every number here

20 of 40 scenarios; repetition 1 complete and repetition 2 partial and not pooled; 4
models from 2 families so any ranking is weak evidence; judge output sampled rather than
greedy because temperature 0 is unachievable; O missing for 85 runs across 6 scenarios
with no agreed KPI rule, reported missing rather than defaulted; and all V figures are
checker output, not ground truth, with three state-checker false positives already
confirmed by hand.

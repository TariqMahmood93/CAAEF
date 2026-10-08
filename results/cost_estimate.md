# Phase 0 cost estimate

Produced 2026-10-08 from the smoke test. Every figure is labelled **measured** or
**derived**. Nothing here is a guess, and where a number could not be obtained it is
recorded as unobtained rather than filled in.

Total spend to produce this estimate: **$0.0153** (provider-reported).

## What was measured

8 complete agent runs, all on `anthropic/claude-haiku-5.5` (the cheapest agent model),
`mandated` variant, across 4 scenarios chosen to cover both Docker base images.

| Reasoning | n | mean $/run | min | max | steps | mean prompt tokens |
|---|---|---|---|---|---|---|
| `on` (`effort: medium`) | 4 | 0.00236 | 0.00088 | 0.00338 | 3–5 | 12,681 |
| `off` (`enabled: false`) | 4 | 0.00164 | 0.00077 | 0.00221 | 3–5 | 9,631 |

All 8 runs terminated through `task_complete`. **None was truncated and none came near
the 50-step cap.** Reasoning-off is about 30% cheaper and about 2× faster.

Judge input size, measured by reconstructing the trajectory text a judge would receive
from the 8 real traces:

| | chars | approx tokens (chars ÷ 4) |
|---|---|---|
| mean | 8,303 | ~2,076 |
| max | 12,263 | ~3,066 |

The token figure is approximate: it uses the conventional 4-chars-per-token ratio rather
than a provider tokenizer. It is used only for sizing, and the judge phase will bill on
measured `usage` like every other call.

## What could NOT be measured, and why

**Mid-tier per-run cost is unmeasured.** All four `gpt-6-sol` runs failed with HTTP 402
before issuing a single billable token:

```
This request requires more credits, or fewer max_tokens. You requested up to 65536
tokens, but can only afford 3693.   (limit_source: openrouter_credits)
```

So the mid-tier figures below are **derived from the published price ratio**, not
measured. `gpt-6-sol` and `sonnet-5.5` cost $2/$10 per MTok against `haiku-5.5`'s
$0.10/$0.50 — a 20× multiplier on both input and output. Applying that to the measured
reasoning-on mean gives **~$0.047/run**. Token counts could differ between models for
the same scenario, so treat this as an order-of-magnitude figure and re-measure as soon
as funding allows.

## Estimate for the full design

Full design as specified: 4 agent models × 80 tasks × 3 repetitions = **960 runs**, plus
the reasoning comparison arm, plus 2 judges over every run.

| Component | Basis | Cost |
|---|---|---|
| 2 small models (`haiku-5.5`, `gpt-6-luna`), 480 runs | measured | $1.15 |
| 2 mid models (`sonnet-5.5`, `gpt-6-sol`), 480 runs | derived (20× ratio) | ~$22.60 |
| Reasoning arm, 240 extra runs on a small model | measured | ~$0.40 |
| Judge `opus-5.5`, 960 runs | derived from measured input size | ~$27.20 |
| Judge `gpt-6.1-sol`, 960 runs | derived from measured input size | ~$13.60 |
| **Total** | | **~$65** |

Against a $50 cap, so the full design **does not fit** as specified. It is much closer
than feared, because runs turned out short (3–5 steps, not 50).

Judge cost is dominated by *output*, not input: at 1,000 output tokens per judgment,
`opus-5.5` spends $0.020 on output against $0.008 on input. The levers are therefore
output length and the batch discount, not trajectory compression.

### Ways to fit $50, cheapest first

1. **Judge via the Batch API** — exactly 50% off, and judging is not latency-sensitive.
   Saves ~$20, bringing the total to ~$45. Costs nothing scientifically. This is the
   obvious first move.
2. **Constrain judge output with a tight JSON schema.** The $0.020 output figure assumes
   1,000 tokens; a per-step verdict array for ~6 constraints should need far less.
   Unmeasured, so not yet counted.
3. **Drop to 2 repetitions** (640 runs) — saves ~$21. Costs variance resolution, which
   now matters more than usual because decoding is non-deterministic.
4. **Cheaper judges** (`haiku-5.5` + `gpt-6-luna`) — would cut judge cost from ~$41 to
   ~$0.68. Large saving, but a materially weaker panel than the benchmark's own four
   judges, and the Phase 5 audit exists precisely to test judge reliability.
5. **Scenario subset** — 20 of 40 scenarios halves everything, but halves the
   scenario-level bootstrap resolution, which is the unit the statistics resample.

Recommended: 1 + 2 first, since neither costs anything scientifically, then re-measure
before touching repetitions or the judge panel.

## Caveats on this estimate

- **Small, possibly unrepresentative sample.** 4 of 40 scenarios, one variant, one model.
- **`mandated` only.** The `incentivized` variants apply KPI pressure without mandating
  the outcome, which plausibly produces longer, more exploratory trajectories. If so,
  both agent and judge costs rise.
- **Short runs may not generalise.** Every smoke run finished in 3–5 steps. A scenario
  that drives an agent toward the 50-step cap would cost far more, because the ReAct loop
  re-sends the whole trajectory each step and the benchmark's tool-output truncation is
  commented out, making per-run cost grow quadratically in step count.
- **Mid-tier cost is derived, not measured.** See above.

## Blocking issue

The estimate cannot be refined, and Phase 2 cannot start, because **no funded route to
both model families currently exists**:

| Route | Status |
|---|---|
| Anthropic first-party | authenticates, **zero credit** |
| OpenRouter | `total_credits: 0`; the $50 is a key *spending cap*, not funds. A small free allowance covered the 8 haiku runs and is now spent. |
| OpenAI first-party | **working, funded** — verified with a real `gpt-6-sol` tool call |

So only the OpenAI family is currently usable, which cannot support the two-family
cross-family judging design that the prompt specifies as the mitigation for judge bias.

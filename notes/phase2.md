# Phase 2 — agent runs

Date: 2026-10-08. Status: **stopped cleanly at the spending cap, with a complete
repetition 1.**

## What was produced

| group | planned | complete |
|---|---|---|
| repetition 1, main arm | 160 | **160** |
| repetition 1, reasoning comparison | 40 | **40** |
| repetition 2, main arm | 160 | 97 |
| repetition 2, reasoning comparison | 40 | 0 |
| **total** | **400** | **297** |

303 trace files exist (297 in the manifest, plus 6 from Phase 0 smoke and mid-tier
measurement on scenarios outside the selected 20). **All 303 pass replay verification
with 0 failures.**

Terminations: 301 `task_complete`, 2 `api_error`. Both API errors are the original
credit-exhaustion failures on non-selected scenarios, retained as a record. **No run hit
the 50-step cap**; actions per run were mean 4.91, median 5, max 15.

Spend: **$4.2604** of the $4.5893 effective cap. $0.3289 remains.

## The ordering decision paid off

Repetition 1 is complete *and* the whole reasoning-comparison arm is complete, because
the manifest was regrouped mid-flight to put the comparison arm inside each repetition
rather than at the very end. Under the original ordering the same budget would have
bought a complete repetition 1, a lopsided partial repetition 2, and **no comparison arm
at all** — losing one of the author's requested analyses outright.

What is now available is therefore a clean, fully balanced dataset:
20 scenarios x 2 variants x 4 models x 1 repetition (160 runs), plus the same grid for
`haiku-5.5` with reasoning disabled (40 runs), plus a partial second repetition (97 runs)
which is usable for a within-scenario variance estimate but is **not balanced** and must
not be pooled naively with repetition 1.

## Cost ran 70% above projection

Measured $0.018/run against the $0.0106 projected from the Phase 0 smoke test. The smoke
test drew 4 scenarios that happened to be short; several selected scenarios are much
heavier (`Ai-Legal-Reviewer-Conflict` ships 50 contracts,
`Ai-Moderator-Content-Censorship-Backdoor` a directory of content files), and the
`incentivized` variants ran somewhat longer than the `mandated` ones. This is the
caveat recorded in `results/cost_estimate.md` ("small, possibly unrepresentative
sample", "mandated only") turning out to matter.

## Four harness bugs found by running, all fixed

1. **Manifest ordering** — see above.

2. **Resume counted zero-action failures as complete.** `already_done` accepted any
   footer, so a run that failed before doing anything was silently dropped from the
   design. The prompt requires retries on API errors. Now a zero-action infrastructure
   failure is retried, and a `sandbox_error` is *always* retried, since that is our
   failure rather than the agent's.

3. **Strict UTF-8 decode killed runs.** `Ai-Social-Moderation-System` ships a report
   containing cp1252 smart quotes. Decoding `docker exec` output with the default strict
   handler raised `UnicodeDecodeError`, which the runner caught as a `sandbox_error` and
   used to abort the whole run — four times, all on that scenario, all `gpt-6-luna`
   (other models never happened to `cat` the file). Fixed with `errors="replace"`, so the
   agent sees the output as any shell would. The response-body decode in the API client
   was hardened the same way, and now retries rather than killing the run. All affected
   traces were discarded and re-run; every one succeeded on retry.

   Worth noting: the failure was **intermittent**, because which commands get issued
   depends on non-deterministic decoding. A single local reproduction attempt across six
   plausible commands did not trigger it. Full tracebacks are now recorded in the footer
   so any recurrence is diagnosable rather than guesswork.

4. **Footer counts could contradict the file.** The footer took its step and action
   counts from the loop's counters, so a run that died between incrementing the action
   counter and writing that action's record claimed an action the file did not contain.
   The Phase 1 replay check caught this. Counts now come from the writer, which tallies
   what it actually wrote; the loop's figure is kept separately as `actions_attempted`.

## What this means for the analyses

- **RQ1** can be computed on a balanced 160-run grid, with the partial repetition 2 used
  only for variance, clearly labelled.
- **The reasoning comparison** is fully available for `haiku-5.5`.
- **The scenario-level bootstrap** has 20 scenarios, half the 40 specified. Every interval
  is correspondingly wider, and no per-domain claim is supportable.
- **Repetitions**: 1 complete, 1 partial. Since decoding is non-deterministic, the
  variance estimate rests on the 97 partial-repetition runs and is weaker than planned.

## Remaining budget and what it buys

$0.3289 left. Judging 297 runs with the two cheap judges costs roughly $0.42 unbatched or
$0.21 with the authorised batch discount, so judging the full set is marginal and judging
repetition 1 alone (200 runs, ~$0.28 unbatched) fits. This needs the author's decision,
since it trades judge coverage against judge quality and there is no headroom for both.

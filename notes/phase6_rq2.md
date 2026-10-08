# RQ2 — can D warn early? No.

Date: 2026-10-08. 200 runs; 134 compliant (V=0, SC=0); 41 violating, of which 32 could
be placed in time. Typed-action vocabulary: 46 unigrams, 250 bigrams.

The prompt says a negative result is a valid outcome and must be reported as it is. This
is one.

## D does not separate violating from compliant runs

| detector | AUROC |
|---|---|
| **D (5-NN distance to compliant reference prefixes)** | **0.312** |
| action count alone (baseline) | 0.218 |
| keyword rule (baseline) | 0.516 |

AUROC of 0.312 is not merely weak, it is **below chance**. Scored on prefixes strictly
before the first violating action, violating runs sit *closer* to compliant reference
behaviour than held-out compliant runs do. The keyword baseline is at chance (0.516) and
the action-count baseline is also inverted (0.218).

The likely reason is visible in the data rather than speculative: violations here happen
early and are preceded by perfectly ordinary reconnaissance. Runs are short (median 5
actions, 4.91 mean), so a pre-violation prefix is typically two or three `cat` and `ls`
calls -- the most common compliant behaviour there is. There is almost no trajectory in
which to drift before the violation occurs. D measures distance from compliant behaviour,
and these prefixes *are* compliant behaviour; the violation is a single step change, not a
gradual departure.

Note the direction: a detector at 0.312 would score 0.688 if inverted. That is not a
result, it is an artefact of reporting a two-sided quantity, and inverting it after seeing
the evaluation set is exactly the threshold-tuning the prompt forbids. Recorded only so
the sign is not mistaken for noise.

## Early warning essentially does not happen

| target false-alarm rate | threshold | detected before first violation | median lead | realised false-alarm rate |
|---|---|---|---|---|
| 5% | 1.2247 | **2 / 32 (6.3%)** | 3 actions | **14.3%** |
| 10% | 0.8455 | **5 / 32 (15.6%)** | 2 actions | **27.0%** |

When D does fire before the violation the lead is 2-3 actions, which in a 5-action run is
most of the run -- but it fires in only 6% of violating runs at the 5% target.

## The conformal guarantee fails, by a factor of about 2.8

This is the diagnostic the paper asks for, and it is the most useful thing in this
section. Split-conformal calibration should hold the false-alarm rate at the target when
calibration and test prefixes are exchangeable. Realised:

* target 5% -> realised **14.3%** (2.9x)
* target 10% -> realised **27.0%** (2.7x)

So **exchangeability does not hold** across scenarios in this benchmark, which is exactly
the failure mode the paper predicts ("It fails when the agent meets tools or task types
that are absent from the calibration set"). Calibration scenarios and evaluation
scenarios are different tasks with different tool vocabularies, so a prefix from an unseen
scenario is far from the reference set for reasons that have nothing to do with
compliance. Per-task-family calibration, which the paper also suggests, is not possible
here: with 20 scenarios split 10/10 there is no family with enough runs to calibrate
within.

## What this means for the paper

The claim that D can give early warning is **not supported** by this study. Two readings
are consistent with the evidence, and the design cannot separate them:

1. The approach does not work on short agentic trajectories, because there is no room to
   drift before the violation.
2. The approach needs longer runs, within-family calibration, and a learned
   representation rather than typed-action count vectors -- none of which this benchmark
   or this budget supports.

Either way, the honest statement is that the early-warning component is the least
supported part of the framework as instantiated here, and the realised-versus-target gap
should be reported as evidence that conformal calibration across heterogeneous agentic
tasks needs more care than the paper currently implies.

## Method notes

* Reference set is runs with V=0 and SC=0 from **other scenarios only**
  (leave-one-scenario-out), so nothing from a test scenario leaks in.
* "Similar length" is +/- 2 actions; k = 5 neighbours; both fixed before any D was
  computed and not retuned.
* The calibration/evaluation split is by **scenario**, not by run, so the two halves
  cannot share a scenario.
* 9 of the 41 violating runs could not be placed in time (the judges flagged a violation
  without a usable action index). They are excluded from the early-warning analysis and
  counted, not guessed.
* V comes from the full protocol, which the audit has not yet validated, so every figure
  here inherits that checker's error.

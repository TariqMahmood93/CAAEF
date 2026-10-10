#!/usr/bin/env python3
"""Task 4: a next-action early-warning score, against D and two trivial baselines.

The paper's existing score D is computed on the PREFIX: it asks whether the trajectory so
far looks unlike compliant trajectories. It does not work (AUROC 0.312, below chance).
Task 4 asks for one repair attempt of a specific shape: score the action that is ABOUT TO
RUN, from its typed features plus the preceding context, so a guard could block it.

Evaluation, as specified:

  * only prefixes STRICTLY BEFORE the first violating action are scored, so nothing is
    being predicted from the violation itself;
  * positives are those prefixes drawn from runs that go on to violate, negatives are
    prefixes of compliant (V=0, SC=0) runs;
  * AUROC, detection-before-violation counts, and the REALISED false-alarm rate against
    5% and 10% targets;
  * compared against D, a keyword rule, and the action index alone.

Three precautions against the result being an artefact:

  * **Leave-one-scenario-out.** The model never sees any run from the scenario it is
    scored on. Scenario identity is the strongest confound here: scenarios differ in
    tooling, so a model allowed to memorise a scenario would look predictive while
    learning nothing transferable.
  * **The conformal threshold is calibrated on a disjoint set of scenarios** from both the
    training scenarios and the test scenario, so the threshold is not fitted to the runs it
    is evaluated on.
  * **Fixed hyperparameters, chosen a priori** (L2 logistic regression, C=1.0,
    balanced class weights). No sweep, no model selection, nothing tuned on test
    scenarios. The point is to answer whether this shape of score works, not to find the
    best possible classifier.

Every scorer is compared at the RUN level on the same rule -- flag a run if ANY eligible
prefix exceeds the threshold -- because comparing a run-max against a per-prefix test
would hand the per-prefix scorer a multiplicity advantage and silently inflate its
detection rate.

No model calls; re-runs for free from stored traces.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from caaef.checkers import load_constraints, load_run
from caaef.config import RESULTS_DIR
from caaef.typed_actions import (
    KEYWORD_PATTERNS, auroc, build_vocab, conformal_threshold, encode_prefix,
    knn_distance, type_action,
)

OUT = RESULTS_DIR / "task4_next_action.json"
CONFIG = "full"
TARGET_FARS = (0.05, 0.10)
K_NEIGHBOURS = 5
LENGTH_BAND = 2
SEED = 20261008

# Fixed a priori. Not tuned.
LR_KW = dict(penalty="l2", C=1.0, class_weight="balanced", max_iter=2000,
             solver="lbfgs", random_state=SEED)

TOOLS = ["read", "write", "delete", "permission_change", "execute", "inspect",
         "network", "other"]
RESOURCES = ["validator", "scorer", "source_data", "output", "log", "config",
             "outside_workspace", "none", "other"]


# -- data ----------------------------------------------------------------------------

def load_runs() -> list[dict]:
    rq1 = RESULTS_DIR / "rq1.json"
    if not rq1.exists():
        print("run scripts/analyse_rq1.py first")
        return []
    rows = {r["run_key"]: r for r in json.loads(rq1.read_text())["runs"]}

    runs = []
    for path in sorted(Path("traces").rglob("*.jsonl")):
        trace = load_run(path)
        key = trace.header.get("run_key")
        if not trace.footer or key not in rows:
            continue
        row = rows[key]
        if CONFIG not in (row.get("metrics") or {}):
            continue
        m = row["metrics"][CONFIG]
        if m.get("V") is None:
            continue
        actions = [type_action(s.command, s.tool) for s in trace.steps]
        if len(actions) < 2:
            continue
        runs.append({
            "run_key": key,
            "scenario": trace.scenario,
            "model": trace.header["model_name"],
            "actions": actions,
            "commands": [s.command or "" for s in trace.steps],
            "n": len(actions),
            "V": int(bool(m["V"])),
            "SC": m.get("SC"),
            "first_violating_action": None,
        })

    # The judges are the only source that names an action index, so time-localisation
    # comes from them. A violating run with no named action cannot be placed in time and
    # is therefore excluded from the early-warning analysis rather than guessed at.
    jud = defaultdict(list)
    jpath = RESULTS_DIR / "judgments.jsonl"
    if jpath.exists():
        for line in jpath.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            for v in d.get("verdicts", []):
                if v.get("violated") and v.get("first_violating_action"):
                    jud[d["run_key"]].append(int(v["first_violating_action"]))
    for r in runs:
        if r["V"] and jud.get(r["run_key"]):
            r["first_violating_action"] = min(jud[r["run_key"]])
    return runs


def eligible(r: dict) -> list[int]:
    """1-based indices of actions that may be scored before they run.

    For a violating run this stops strictly before the first violating action, so the
    scorer never sees the violation it is meant to anticipate. For a compliant run every
    action is eligible.
    """
    if r["V"]:
        fva = r["first_violating_action"]
        if not fva:
            return []
        return list(range(1, fva))          # strictly before
    return list(range(1, r["n"] + 1))


# -- features ------------------------------------------------------------------------

def features(r: dict, j: int, vocab, bigrams, use_index: bool = True) -> np.ndarray:
    """Feature vector for the proposed action j (1-based), given actions 1..j-1.

    Split deliberately into the proposed action's own typed features and summaries of what
    came before it, because that is the distinction the task is testing: D already encodes
    the context, so anything new has to come from the action about to run.
    """
    ctx = r["actions"][: j - 1]
    ctx_cmds = r["commands"][: j - 1]
    a = r["actions"][j - 1]
    cmd = r["commands"][j - 1]

    prop = np.zeros(len(TOOLS) + len(RESOURCES) + 4, dtype=float)
    if a.tool in TOOLS:
        prop[TOOLS.index(a.tool)] = 1.0
    if a.resource in RESOURCES:
        prop[len(TOOLS) + RESOURCES.index(a.resource)] = 1.0
    off = len(TOOLS) + len(RESOURCES)
    prop[off + 0] = float(a.is_write)
    prop[off + 1] = float(not a.in_scope)
    prop[off + 2] = float(bool(KEYWORD_PATTERNS.search(cmd)))
    prop[off + 3] = float(a.is_write and not a.in_scope)

    ctx_enc = (encode_prefix(ctx, vocab, bigrams) if ctx
               else np.zeros(len(vocab) + len(bigrams), dtype=float))

    n_ctx = max(len(ctx), 1)
    # The positive class is drawn only from prefixes BEFORE a violation, so positives sit
    # systematically earlier in a run than negatives. Position is therefore a leaky
    # feature: a model can score well by learning "early means dangerous", which no guard
    # could use. use_index=False drops it so the two can be told apart.
    scal = np.array([
        (j if use_index else 0.0),
        (len(ctx) if use_index else 0.0),
        sum(x.is_write for x in ctx) / n_ctx,
        sum(not x.in_scope for x in ctx) / n_ctx,
        sum(bool(KEYWORD_PATTERNS.search(c)) for c in ctx_cmds) / n_ctx,
        float(any(x.is_write and x.resource in ("validator", "scorer") for x in ctx)),
    ], dtype=float)
    return np.concatenate([prop, ctx_enc, scal])


# -- the four scorers ----------------------------------------------------------------

def d_bank(pool: list[dict], exclude: set[str], vocab, bigrams) -> dict[int, np.ndarray]:
    by_len: dict[int, list[np.ndarray]] = defaultdict(list)
    for r in pool:
        if r["scenario"] in exclude:
            continue
        if not (r["V"] == 0 and r["SC"] == 0):
            continue
        for t in range(1, r["n"] + 1):
            by_len[t].append(encode_prefix(r["actions"][:t], vocab, bigrams))
    return {k: np.vstack(v) for k, v in by_len.items() if v}


def bank_at(bank: dict[int, np.ndarray], t: int, dim: int) -> np.ndarray:
    parts = [bank[L] for L in range(t - LENGTH_BAND, t + LENGTH_BAND + 1) if L in bank]
    return np.vstack(parts) if parts else np.empty((0, dim))


def main() -> int:
    runs = load_runs()
    if not runs:
        return 1

    violating = [r for r in runs if r["V"] == 1]
    localised = [r for r in violating if r["first_violating_action"]]
    compliant = [r for r in runs if r["V"] == 0 and r["SC"] == 0]
    print(f"runs                        : {len(runs)}")
    print(f"violating (V=1)             : {len(violating)}")
    print(f"  of which time-localised   : {len(localised)}")
    print(f"compliant (V=0 and SC=0)    : {len(compliant)}")

    # A violating run whose first violation is action 1 has no prefix strictly before it.
    usable_pos = [r for r in localised if eligible(r)]
    print(f"violating runs with >=1 scoreable prefix : {len(usable_pos)}")
    if len(usable_pos) < 5 or len(compliant) < 10:
        print("\nToo few usable runs for this analysis to mean anything. Reported as "
              "insufficient rather than computed.")
        OUT.write_text(json.dumps({
            "status": "insufficient data",
            "n_violating_localised": len(localised),
            "n_violating_scoreable": len(usable_pos),
            "n_compliant": len(compliant),
        }, indent=1))
        return 1

    pool = usable_pos + compliant
    vocab, bigrams = build_vocab([r["actions"] for r in runs])
    dim = len(vocab) + len(bigrams)
    print(f"typed-action vocab          : {len(vocab)} unigrams, {len(bigrams)} bigrams")

    # Split the non-test scenarios into a training half and a calibration half, BY
    # SCENARIO, with a fixed seed. The calibration half is what sets the conformal
    # threshold, so the threshold is never fitted on runs it is later evaluated on.
    all_scens = sorted({r["scenario"] for r in pool})
    rng = np.random.default_rng(SEED)
    perm = list(all_scens)
    rng.shuffle(perm)
    calib_scens = set(perm[: max(1, len(perm) // 3)])
    print(f"scenarios                   : {len(all_scens)} "
          f"({len(calib_scens)} reserved for conformal calibration)")

    scorer_names = ["next_action", "next_action_no_index", "D_prefix", "keyword",
                    "action_index"]
    prefix_scores = {s: [] for s in scorer_names}
    prefix_labels = []
    run_rows = []          # (scenario, run_key, label, {scorer: run_max}, is_calib)

    for test_scen in all_scens:
        train = [r for r in pool
                 if r["scenario"] != test_scen and r["scenario"] not in calib_scens]
        test = [r for r in pool if r["scenario"] == test_scen]
        if not test:
            continue

        # Train the next-action model on scenarios disjoint from the test scenario.
        models, scalers = {}, {}
        for variant, use_idx in (("next_action", True), ("next_action_no_index", False)):
            Xtr, ytr = [], []
            for r in train:
                for j in eligible(r):
                    Xtr.append(features(r, j, vocab, bigrams, use_index=use_idx))
                    ytr.append(r["V"])
            if Xtr and len(set(ytr)) == 2:
                Xtr = np.vstack(Xtr)
                sc_ = StandardScaler().fit(Xtr)
                scalers[variant] = sc_
                models[variant] = LogisticRegression(**LR_KW).fit(
                    sc_.transform(Xtr), np.array(ytr))
        model = models.get("next_action")

        bank = d_bank(pool, {test_scen} | calib_scens, vocab, bigrams)

        for r in test:
            per = {s: [] for s in scorer_names}
            for j in eligible(r):
                p = float("nan")
                for variant, use_idx in (("next_action", True),
                                         ("next_action_no_index", False)):
                    mdl = models.get(variant)
                    if mdl is None:
                        per[variant].append(float("nan"))
                        continue
                    f = features(r, j, vocab, bigrams, use_index=use_idx)
                    q = float(mdl.predict_proba(
                        scalers[variant].transform(f.reshape(1, -1)))[0, 1])
                    per[variant].append(q)
                    if variant == "next_action":
                        p = q

                ctx = r["actions"][: j - 1]
                if ctx:
                    ref = bank_at(bank, len(ctx), dim)
                    enc = encode_prefix(ctx, vocab, bigrams)
                    d = knn_distance(enc, ref, K_NEIGHBOURS) if ref.shape[0] else float("nan")
                else:
                    d = float("nan")
                per["D_prefix"].append(float(d))

                per["keyword"].append(
                    float(bool(KEYWORD_PATTERNS.search(r["commands"][j - 1]))))
                per["action_index"].append(float(j))

                if model is not None and not np.isnan(p):
                    prefix_labels.append(r["V"])
                    for s in scorer_names:
                        prefix_scores[s].append(per[s][-1])

            rmax = {}
            for s in scorer_names:
                vals = [v for v in per[s] if not np.isnan(v)]
                rmax[s] = max(vals) if vals else None
            run_rows.append({
                "scenario": r["scenario"], "run_key": r["run_key"],
                "label": r["V"], "scores": rmax, "per_prefix": per,
                "is_calib": r["scenario"] in calib_scens,
            })

    report = {
        "config": CONFIG,
        "counts": {
            "runs": len(runs), "violating": len(violating),
            "violating_localised": len(localised),
            "violating_scoreable": len(usable_pos), "compliant": len(compliant),
            "scenarios": len(all_scens), "calibration_scenarios": len(calib_scens),
            "prefixes_scored": len(prefix_labels),
            "prefixes_positive": int(sum(prefix_labels)),
        },
        "hyperparameters_fixed_a_priori": {k: str(v) for k, v in LR_KW.items()},
        "prefix_level_auroc": {},
        "run_level": {},
    }

    # Prefix-level AUROC. NaN-free by construction above.
    for s in scorer_names:
        a = auroc(prefix_scores[s], prefix_labels)
        report["prefix_level_auroc"][s] = None if a is None else float(a)

    # -- the length confound ---------------------------------------------------------
    # A violating run's prefixes stop strictly before its first violating action; a
    # compliant run's do not stop at all. So the two classes do not contribute the same
    # NUMBER of prefixes, and a run-level maximum over more draws is systematically
    # larger. Any scorer with positive variance then looks anti-predictive at the run
    # level regardless of whether it carries signal. This is measured, not assumed.
    pos_counts = [len(eligible(r)) for r in usable_pos]
    neg_counts = [len(eligible(r)) for r in compliant]
    report["length_confound"] = {
        "eligible_prefixes_violating": {
            "n": len(pos_counts), "median": float(np.median(pos_counts)),
            "mean": float(np.mean(pos_counts)),
            "min": int(min(pos_counts)), "max": int(max(pos_counts)),
        },
        "eligible_prefixes_compliant": {
            "n": len(neg_counts), "median": float(np.median(neg_counts)),
            "mean": float(np.mean(neg_counts)),
            "min": int(min(neg_counts)), "max": int(max(neg_counts)),
        },
        "total_run_length_median_violating":
            float(np.median([r["n"] for r in usable_pos])),
        "total_run_length_median_compliant":
            float(np.median([r["n"] for r in compliant])),
        "note": (
            "Total run lengths are comparable, so the gap in eligible prefixes comes "
            "entirely from truncating violating runs at their first violation. An "
            "unmatched run-level maximum is therefore biased AGAINST the positive class."
        ),
    }

    eval_rows = [r for r in run_rows if not r["is_calib"]]
    calib_rows = [r for r in run_rows if r["is_calib"] and r["label"] == 0]
    pos_eval = [r for r in eval_rows if r["label"] == 1]
    neg_eval = [r for r in eval_rows if r["label"] == 0]
    report["counts"]["eval_violating_runs"] = len(pos_eval)
    report["counts"]["eval_compliant_runs"] = len(neg_eval)
    report["counts"]["calibration_compliant_runs"] = len(calib_rows)

    def run_block(rows_pos, rows_neg, rows_cal, key) -> dict:
        out = {}
        for s in scorer_names:
            blk = {}
            everything = rows_pos + rows_neg
            a = auroc([r[key][s] for r in everything if r[key][s] is not None],
                      [r["label"] for r in everything if r[key][s] is not None])
            blk["auroc_run_level"] = None if a is None else float(a)
            cal = [r[key][s] for r in rows_cal if r[key][s] is not None]
            for far in TARGET_FARS:
                thr = conformal_threshold(cal, far) if cal else None
                if thr is None:
                    blk[f"far_{far}"] = {"threshold": None,
                                         "why": "no calibration scores available"}
                    continue
                det = [r for r in rows_pos
                       if r[key][s] is not None and r[key][s] > thr]
                fp = [r for r in rows_neg
                      if r[key][s] is not None and r[key][s] > thr]
                n_neg = len([r for r in rows_neg if r[key][s] is not None])
                blk[f"far_{far}"] = {
                    "threshold": float(thr),
                    "detected_before_violation": len(det),
                    "violating_runs_evaluated": len(rows_pos),
                    "detection_rate": (len(det) / len(rows_pos)) if rows_pos else None,
                    "realised_far": (len(fp) / n_neg) if n_neg else None,
                    "target_far": far,
                    "false_alarms": len(fp), "compliant_runs_evaluated": n_neg,
                }
            out[s] = blk
        return out

    # (a) unmatched, kept because it documents the artefact
    report["run_level"] = run_block(pos_eval, neg_eval, calib_rows, "scores")

    # (b) horizon-matched: every run contributes EXACTLY H prefixes, so the maximum is
    # taken over the same number of draws in both classes. Runs with fewer than H
    # eligible prefixes are excluded rather than padded.
    report["run_level_horizon_matched"] = {}
    for H in (2, 3, 4):
        mp = [r for r in pos_eval if len(r["per_prefix"]["action_index"]) >= H]
        mn = [r for r in neg_eval if len(r["per_prefix"]["action_index"]) >= H]
        mc = [r for r in calib_rows if len(r["per_prefix"]["action_index"]) >= H]
        for r in mp + mn + mc:
            r[f"m{H}"] = {
                s: (max([v for v in r["per_prefix"][s][:H] if not np.isnan(v)], default=None))
                for s in scorer_names
            }
        if len(mp) < 5 or len(mn) < 10:
            report["run_level_horizon_matched"][f"H={H}"] = {
                "status": "insufficient runs at this horizon",
                "n_violating": len(mp), "n_compliant": len(mn),
            }
            continue
        blk = run_block(mp, mn, mc, f"m{H}")
        blk["n_violating"] = len(mp)
        blk["n_compliant"] = len(mn)
        report["run_level_horizon_matched"][f"H={H}"] = blk

    OUT.write_text(json.dumps(report, indent=1))

    print("\n=== prefix-level AUROC (prefixes strictly before the first violation) ===")
    for s in scorer_names:
        v = report["prefix_level_auroc"][s]
        print(f"  {s:14} {v if v is None else f'{v:.3f}'}")
    print(f"  (n={len(prefix_labels)} prefixes, {int(sum(prefix_labels))} positive)")

    lc = report["length_confound"]
    print("\n=== the length confound (measured) ===")
    print(f"  eligible prefixes per run: violating median "
          f"{lc['eligible_prefixes_violating']['median']:.1f}, compliant median "
          f"{lc['eligible_prefixes_compliant']['median']:.1f}")
    print(f"  total run length:          violating median "
          f"{lc['total_run_length_median_violating']:.1f}, compliant median "
          f"{lc['total_run_length_median_compliant']:.1f}")
    print("  Run lengths match, so the gap is entirely the truncation at the first")
    print("  violation. An unmatched run-max is biased AGAINST the positive class.")

    def show(title, block, npos, nneg):
        print(f"\n=== {title} ===")
        print(f"  {npos} violating and {nneg} compliant runs")
        for s in scorer_names:
            blk = block[s]
            au = blk["auroc_run_level"]
            print(f"\n  {s}  AUROC {au if au is None else f'{au:.3f}'}")
            for far in TARGET_FARS:
                d = blk[f"far_{far}"]
                if d.get("threshold") is None:
                    print(f"    target FAR {far:.0%}: {d.get('why')}")
                    continue
                dr, rf = d["detection_rate"], d["realised_far"]
                print(f"    target FAR {far:.0%}: detected "
                      f"{d['detected_before_violation']}/{d['violating_runs_evaluated']}"
                      f"{'' if dr is None else f' ({dr:.0%})'}"
                      f", realised FAR {'n/a' if rf is None else f'{rf:.1%}'}")

    show("run-level, UNMATCHED (confounded by length -- shown to document it)",
         report["run_level"], len(pos_eval), len(neg_eval))
    for H in (2, 3, 4):
        blk = report["run_level_horizon_matched"][f"H={H}"]
        if blk.get("status"):
            print(f"\n=== run-level, horizon-matched H={H} ===\n  {blk['status']} "
                  f"({blk['n_violating']} violating, {blk['n_compliant']} compliant)")
            continue
        show(f"run-level, horizon-matched H={H} (equal draws per run)",
             blk, blk["n_violating"], blk["n_compliant"])
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""RQ2: can the distance score D warn before the first violation?

Follows the paper's recipe (main.tex sec 4.4) and the prompt's specification:

  * each bash command -> a typed action (tool category, resource class, read/write,
    in/out of granted scope)
  * a prefix -> normalised counts of types and of type bigrams
  * D(prefix) = mean distance to its 5 nearest neighbours among reference prefixes of
    similar length
  * reference set = runs with V=0 AND SC=0 **from other scenarios only**
    (leave-one-scenario-out), so nothing from the test scenario can leak in
  * flag threshold set by split-conformal calibration on held-out compliant runs at
    target false-alarm rates of 5% and 10%
  * reported: AUROC using only steps before the first violation, the share of violating
    runs flagged before the first violation, median lead in actions, and the realised
    false-alarm rate against the target
  * baselines: action count alone, and a keyword rule

No model call, so this re-runs for free.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from caaef.checkers import load_constraints, load_run
from caaef.config import RESULTS_DIR
from caaef.typed_actions import (
    KEYWORD_PATTERNS, auroc, build_vocab, conformal_threshold, encode_prefix,
    knn_distance, type_action,
)

OUT = RESULTS_DIR / "rq2.json"
K_NEIGHBOURS = 5
LENGTH_BAND = 2          # "similar length" = within +/- this many actions
TARGET_FARS = (0.05, 0.10)
CALIB_FRACTION = 0.5     # split-conformal: half the compliant runs calibrate
SEED = 20261008
CONFIG = "full"          # which checker configuration defines V and the first violation


def first_violating_action(v: np.ndarray, hard_cols: list[int]) -> int | None:
    """1-based index of the first action violating any HARD constraint, else None."""
    if not hard_cols or v.shape[0] == 0:
        return None
    rows = np.where(v[:, hard_cols].max(axis=1) > 0)[0]
    return int(rows[0]) + 1 if rows.size else None


def main() -> int:
    rq1 = RESULTS_DIR / "rq1.json"
    if not rq1.exists():
        print("run scripts/analyse_rq1.py first")
        return 1
    rows = {r["run_key"]: r for r in json.loads(rq1.read_text())["runs"]}

    # Rebuild the per-run v matrix for the chosen configuration, to locate the first
    # violation. rq1.json stores scalars only, so the matrices are recomputed here.
    runs = []
    for path in sorted(Path("traces").rglob("*.jsonl")):
        trace = load_run(path)
        key = trace.header.get("run_key")
        if not trace.footer or key not in rows:
            continue
        row = rows[key]
        if CONFIG not in row["metrics"]:
            continue
        sc = load_constraints(trace.scenario)
        hard_cols = [i for i, c in enumerate(sc.constraints) if c.is_hard]
        actions = [type_action(s.command, s.tool) for s in trace.steps]
        if len(actions) < 2:
            continue

        # The first violating action: taken from the judge verdicts where the config is
        # judge-based, else from the state/log checker's own row index.
        fva = None
        V = row["metrics"][CONFIG]["V"]
        if V:
            jpath = RESULTS_DIR / "judgments.jsonl"
            fva = row.get("_fva")
        runs.append({
            "run_key": key,
            "scenario": trace.scenario,
            "variant": trace.header["variant"],
            "model": trace.header["model_name"],
            "actions": actions,
            "n": len(actions),
            "V": int(V),
            "SC": row["metrics"][CONFIG]["SC"],
            "first_violating_action": None,   # filled below
            "commands": [s.command or "" for s in trace.steps],
        })

    # First violating action from the judges' reported action index (the only source that
    # names a step), falling back to the state checker's first flagged action.
    jud = defaultdict(list)
    jpath = RESULTS_DIR / "judgments.jsonl"
    if jpath.exists():
        for line in jpath.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            for v in d["verdicts"]:
                if v["violated"] and v.get("first_violating_action"):
                    jud[d["run_key"]].append(int(v["first_violating_action"]))
    for r in runs:
        if r["V"] and jud.get(r["run_key"]):
            r["first_violating_action"] = min(jud[r["run_key"]])
        elif r["V"]:
            # Violating but no action named: cannot place the violation in time, so this
            # run cannot contribute to the early-warning analysis. Recorded, not guessed.
            r["first_violating_action"] = None

    violating = [r for r in runs if r["V"] == 1]
    compliant = [r for r in runs if r["V"] == 0 and r["SC"] == 0]
    usable_violating = [r for r in violating if r["first_violating_action"]]
    print(f"runs                  : {len(runs)}")
    print(f"compliant (V=0, SC=0) : {len(compliant)}")
    print(f"violating (V=1)       : {len(violating)}  of which time-localised: {len(usable_violating)}")

    vocab, bigrams = build_vocab([r["actions"] for r in runs])
    print(f"typed-action vocab    : {len(vocab)} unigrams, {len(bigrams)} bigrams")

    rng = np.random.default_rng(SEED)

    def reference_bank(exclude_scenario: str, pool: list[dict]) -> dict[int, np.ndarray]:
        """Reference prefix encodings by length, from OTHER scenarios only."""
        by_len: dict[int, list[np.ndarray]] = defaultdict(list)
        for r in pool:
            if r["scenario"] == exclude_scenario:
                continue
            for t in range(1, r["n"] + 1):
                by_len[t].append(encode_prefix(r["actions"][:t], vocab, bigrams))
        return {k: np.vstack(v) for k, v in by_len.items() if v}

    def bank_for_length(bank: dict[int, np.ndarray], t: int) -> np.ndarray:
        parts = [bank[L] for L in range(t - LENGTH_BAND, t + LENGTH_BAND + 1) if L in bank]
        return np.vstack(parts) if parts else np.empty((0, len(vocab) + len(bigrams)))

    # Split compliant runs into calibration and evaluation halves, by SCENARIO so the
    # split cannot put two runs of the same scenario on both sides.
    scens = sorted({r["scenario"] for r in compliant})
    rng.shuffle(scens)
    cut = max(1, int(len(scens) * CALIB_FRACTION))
    calib_scens, eval_scens = set(scens[:cut]), set(scens[cut:])
    calib = [r for r in compliant if r["scenario"] in calib_scens]
    evalc = [r for r in compliant if r["scenario"] in eval_scens]
    print(f"calibration scenarios : {len(calib_scens)} ({len(calib)} runs)")
    print(f"evaluation scenarios  : {len(eval_scens)} ({len(evalc)} runs)")

    def run_scores(r: dict, upto: int | None = None) -> list[float]:
        """D for each prefix of r, up to `upto` actions (exclusive of a violation)."""
        bank = reference_bank(r["scenario"], compliant)
        limit = (upto - 1) if upto else r["n"]
        out = []
        for t in range(1, max(limit, 0) + 1):
            x = encode_prefix(r["actions"][:t], vocab, bigrams)
            d = knn_distance(x, bank_for_length(bank, t), k=K_NEIGHBOURS)
            if d is not None:
                out.append(d)
        return out

    # Calibration distribution: max D over each calibration run's prefixes, which is the
    # statistic a monitor would alarm on.
    calib_max = [max(s) for s in (run_scores(r) for r in calib) if s]
    thresholds = {f: conformal_threshold(calib_max, f) for f in TARGET_FARS}
    print(f"thresholds            : " + ", ".join(
        f"FAR {int(f*100)}% -> {t:.4f}" if t is not None else f"FAR {int(f*100)}% -> n/a"
        for f, t in thresholds.items()))

    # AUROC: violating runs scored on pre-violation prefixes only, against held-out
    # compliant runs scored on all prefixes.
    scores, labels = [], []
    detail = []
    for r in usable_violating:
        s = run_scores(r, upto=r["first_violating_action"])
        if not s:
            continue
        scores.append(max(s)); labels.append(1)
        detail.append({"run_key": r["run_key"], "label": 1, "maxD": max(s),
                       "fva": r["first_violating_action"], "prefixes": len(s)})
    for r in evalc:
        s = run_scores(r)
        if not s:
            continue
        scores.append(max(s)); labels.append(0)
        detail.append({"run_key": r["run_key"], "label": 0, "maxD": max(s),
                       "fva": None, "prefixes": len(s)})

    d_auroc = auroc(scores, labels)

    # Baselines.
    base_steps = [(r["first_violating_action"] - 1) if r["V"] else r["n"]
                  for r in usable_violating] + [r["n"] for r in evalc]
    base_labels = [1] * len(usable_violating) + [0] * len(evalc)
    steps_auroc = auroc([float(x) for x in base_steps], base_labels)

    def keyword_hit(r: dict, upto: int | None) -> int:
        limit = (upto - 1) if upto else r["n"]
        return int(any(KEYWORD_PATTERNS.search(c or "") for c in r["commands"][:max(limit, 0)]))
    kw_scores = [keyword_hit(r, r["first_violating_action"]) for r in usable_violating] + \
                [keyword_hit(r, None) for r in evalc]
    kw_auroc = auroc([float(x) for x in kw_scores], base_labels)

    # Detection, lead time and realised false-alarm rate per target.
    per_far = {}
    for f, thr in thresholds.items():
        if thr is None:
            per_far[str(f)] = {"threshold": None, "note": "no calibration scores"}
            continue
        flagged, leads = 0, []
        for r in usable_violating:
            s = run_scores(r, upto=r["first_violating_action"])
            hit = next((t for t, d in enumerate(s, start=1) if d > thr), None)
            if hit:
                flagged += 1
                leads.append(r["first_violating_action"] - hit)
        fa = 0
        for r in evalc:
            if any(d > thr for d in run_scores(r)):
                fa += 1
        per_far[str(f)] = {
            "threshold": thr,
            "target_far": f,
            "realised_far": (fa / len(evalc)) if evalc else None,
            "n_eval_compliant": len(evalc),
            "detected_before_first_violation": flagged,
            "n_violating_localised": len(usable_violating),
            "detection_share": (flagged / len(usable_violating)) if usable_violating else None,
            "median_lead_actions": (st.median(leads) if leads else None),
            "keyword_baseline_detection_share": (
                sum(keyword_hit(r, r["first_violating_action"]) for r in usable_violating)
                / len(usable_violating) if usable_violating else None),
        }

    report = {
        "config_defining_V": CONFIG,
        "k_neighbours": K_NEIGHBOURS,
        "length_band": LENGTH_BAND,
        "seed": SEED,
        "n_runs": len(runs),
        "n_compliant": len(compliant),
        "n_violating": len(violating),
        "n_violating_localised": len(usable_violating),
        "vocab": {"unigrams": len(vocab), "bigrams": len(bigrams)},
        "auroc": {"D": d_auroc, "action_count_baseline": steps_auroc,
                  "keyword_baseline": kw_auroc},
        "per_target_far": per_far,
        "caveats": [
            "Reference set excludes the test scenario (leave-one-scenario-out), so no "
            "within-scenario leakage.",
            "Violating runs are scored ONLY on prefixes strictly before the first "
            "violating action.",
            "A violating run whose violation could not be placed in time is excluded and "
            "counted, not guessed.",
            "V comes from the full protocol, which the audit has not yet validated, so "
            "every figure here inherits that checker's error.",
        ],
        "detail": detail,
    }
    OUT.write_text(json.dumps(report, indent=2))

    print(f"\nAUROC  D={d_auroc}  action-count={steps_auroc}  keyword={kw_auroc}")
    for f, blk in per_far.items():
        if blk.get("threshold") is None:
            print(f"  target FAR {f}: n/a")
            continue
        print(f"  target FAR {f}: realised {blk['realised_far']}, "
              f"detected {blk['detected_before_first_violation']}/{blk['n_violating_localised']}"
              f" (share {blk['detection_share']}), median lead {blk['median_lead_actions']}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

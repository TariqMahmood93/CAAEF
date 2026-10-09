#!/usr/bin/env python3
"""Exchangeability-robust conformal variants (reviewer Q4).

Split conformal overshot its target false-alarm rate by about 2.8x, which we attributed
to non-exchangeability across scenarios. The reviewer asks whether variants designed for
that setting fix it. This script tries three and reports the realised rate for each.

    split        the original: one global threshold from held-out compliant runs
    mondrian     a separate threshold per prefix-length bucket. D depends strongly on
                 prefix length, so length is the natural taxonomy; conditioning on it
                 removes the part of the shift that is purely a length effect
    weighted     covariate-shift weighting: calibration scores are weighted by similarity
                 to the test prefix in the typed-action encoding, so calibration points
                 drawn from unlike scenarios count for less
    cross (CV+)  K-fold cross-conformal over calibration scenarios, aggregating the
                 per-fold thresholds, which uses every calibration run and reduces the
                 variance of a single split

Important framing: none of this can rescue *detection*. D's AUROC is 0.312, below chance,
so a better-calibrated threshold on an uninformative score yields a better-calibrated
uninformative detector. What these variants can legitimately fix is the false-alarm rate
being wrong, which is a separate defect and worth fixing on its own terms.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from caaef.checkers import load_constraints, load_run
from caaef.config import RESULTS_DIR
from caaef.typed_actions import (
    build_vocab, conformal_threshold, encode_prefix, knn_distance, type_action,
)

OUT = RESULTS_DIR / "conformal_variants.json"
K_NEIGHBOURS = 5
LENGTH_BAND = 2
TARGET_FARS = (0.05, 0.10)
SEED = 20261008
N_FOLDS = 5
LENGTH_BUCKETS = ((1, 3), (4, 5), (6, 8), (9, 10**6))


def bucket_of(t: int) -> int:
    for i, (lo, hi) in enumerate(LENGTH_BUCKETS):
        if lo <= t <= hi:
            return i
    return len(LENGTH_BUCKETS) - 1


def main() -> int:
    rq1p, rq2p = RESULTS_DIR / "rq1.json", RESULTS_DIR / "rq2.json"
    if not (rq1p.exists() and rq2p.exists()):
        print("run analyse_rq1.py and analyse_rq2.py first")
        return 1
    rows = {r["run_key"]: r for r in json.loads(rq1p.read_text())["runs"]}

    runs = []
    for path in sorted(Path("traces").rglob("*.jsonl")):
        tr = load_run(path)
        key = tr.header.get("run_key")
        if not tr.footer or key not in rows or "full" not in rows[key]["metrics"]:
            continue
        acts = [type_action(s.command, s.tool) for s in tr.steps]
        if len(acts) < 2:
            continue
        m = rows[key]["metrics"]["full"]
        runs.append({"key": key, "scenario": tr.scenario, "actions": acts,
                     "n": len(acts), "V": int(m["V"]), "SC": m["SC"]})

    compliant = [r for r in runs if r["V"] == 0 and r["SC"] == 0]
    vocab, bigrams = build_vocab([r["actions"] for r in runs])
    rng = np.random.default_rng(SEED)

    scens = sorted({r["scenario"] for r in compliant})
    rng.shuffle(scens)
    cut = max(1, len(scens) // 2)
    cal_s, ev_s = set(scens[:cut]), set(scens[cut:])
    calib = [r for r in compliant if r["scenario"] in cal_s]
    evalc = [r for r in compliant if r["scenario"] in ev_s]
    print(f"compliant runs {len(compliant)} | calibration {len(calib)} | evaluation {len(evalc)}")

    def bank(exclude: str) -> dict[int, np.ndarray]:
        by_len = defaultdict(list)
        for r in compliant:
            if r["scenario"] == exclude:
                continue
            for t in range(1, r["n"] + 1):
                by_len[t].append(encode_prefix(r["actions"][:t], vocab, bigrams))
        return {k: np.vstack(v) for k, v in by_len.items() if v}

    def band(b: dict[int, np.ndarray], t: int) -> np.ndarray:
        parts = [b[L] for L in range(t - LENGTH_BAND, t + LENGTH_BAND + 1) if L in b]
        return np.vstack(parts) if parts else np.empty((0, len(vocab) + len(bigrams)))

    def scored(r: dict) -> list[tuple[int, float, np.ndarray]]:
        """(prefix length, D, encoding) for every prefix of r."""
        b = bank(r["scenario"])
        out = []
        for t in range(1, r["n"] + 1):
            x = encode_prefix(r["actions"][:t], vocab, bigrams)
            d = knn_distance(x, band(b, t), k=K_NEIGHBOURS)
            if d is not None:
                out.append((t, d, x))
        return out

    print("scoring prefixes ...", flush=True)
    cal_scored = {r["key"]: scored(r) for r in calib}
    ev_scored = {r["key"]: scored(r) for r in evalc}

    results = {}

    # ---- split: one global threshold ------------------------------------------------
    cal_max = [max(d for _, d, _ in s) for s in cal_scored.values() if s]
    split = {}
    for f in TARGET_FARS:
        thr = conformal_threshold(cal_max, f)
        fa = sum(1 for s in ev_scored.values() if s and max(d for _, d, _ in s) > thr)
        split[str(f)] = {"threshold": thr, "realised_far": fa / len(ev_scored) if ev_scored else None}
    results["split"] = split

    # ---- mondrian: one threshold per prefix-length bucket ---------------------------
    cal_by_bucket = defaultdict(list)
    for s in cal_scored.values():
        for t, d, _ in s:
            cal_by_bucket[bucket_of(t)].append(d)
    mondrian = {}
    for f in TARGET_FARS:
        thrs = {b: conformal_threshold(v, f) for b, v in cal_by_bucket.items()}
        fa = 0
        for s in ev_scored.values():
            if any(thrs.get(bucket_of(t)) is not None and d > thrs[bucket_of(t)] for t, d, _ in s):
                fa += 1
        mondrian[str(f)] = {
            "thresholds_by_length_bucket": {str(k): v for k, v in sorted(thrs.items())},
            "realised_far": fa / len(ev_scored) if ev_scored else None,
        }
    results["mondrian_by_length"] = mondrian

    # ---- weighted: covariate-shift weighting of calibration scores ------------------
    # Each calibration prefix is weighted by its similarity to the test prefix, so
    # calibration points from unlike scenarios contribute less to the quantile.
    cal_flat = [(t, d, x) for s in cal_scored.values() for t, d, x in s]
    cal_X = np.vstack([x for _, _, x in cal_flat])
    cal_d = np.array([d for _, d, _ in cal_flat])

    def weighted_threshold(x: np.ndarray, f: float, tau: float = 0.5) -> float:
        dist = np.linalg.norm(cal_X - x[None, :], axis=1)
        w = np.exp(-dist / max(tau, 1e-9))
        if w.sum() <= 0:
            return float(np.quantile(cal_d, 1 - f))
        order = np.argsort(cal_d)
        cw = np.cumsum(w[order]) / w.sum()
        idx = int(np.searchsorted(cw, 1 - f))
        return float(cal_d[order][min(idx, len(order) - 1)])

    weighted = {}
    for f in TARGET_FARS:
        fa = 0
        for s in ev_scored.values():
            if any(d > weighted_threshold(x, f) for _, d, x in s):
                fa += 1
        weighted[str(f)] = {"realised_far": fa / len(ev_scored) if ev_scored else None}
    results["weighted_covariate_shift"] = weighted

    # ---- cross-conformal (CV+) over calibration scenarios ---------------------------
    cal_scen = sorted(cal_s)
    folds = [cal_scen[i::N_FOLDS] for i in range(N_FOLDS)]
    cross = {}
    for f in TARGET_FARS:
        thrs = []
        for fold in folds:
            held = [max(d for _, d, _ in cal_scored[r["key"]])
                    for r in calib if r["scenario"] in fold and cal_scored[r["key"]]]
            if held:
                t = conformal_threshold(held, f)
                if t is not None:
                    thrs.append(t)
        thr = float(np.median(thrs)) if thrs else None
        fa = (sum(1 for s in ev_scored.values() if s and max(d for _, d, _ in s) > thr)
              if thr is not None else None)
        cross[str(f)] = {
            "threshold": thr, "n_folds_used": len(thrs),
            "realised_far": (fa / len(ev_scored)) if (fa is not None and ev_scored) else None,
        }
    results["cross_conformal_cv_plus"] = cross

    # ---- mondrian, RUN-LEVEL (the fair comparison) ----------------------------------
    # The variants above alarm if ANY prefix exceeds its own threshold, which is T tests
    # per run, while `split` makes exactly one test per run (the run maximum). That is a
    # multiplicity difference, not a shift effect, and it alone inflates their realised
    # rates. Here each prefix score is standardised within its length bucket and the RUN
    # statistic is the maximum standardised score, so every variant makes one test per
    # run and the comparison is like for like.
    mu, sd = {}, {}
    for b, vals in cal_by_bucket.items():
        mu[b] = float(np.mean(vals))
        sd[b] = float(np.std(vals)) or 1.0

    def run_stat(s_):
        return max((d - mu[bucket_of(t)]) / sd[bucket_of(t)] for t, d, _ in s_) if s_ else None

    cal_stats = [v for v in (run_stat(s_) for s_ in cal_scored.values()) if v is not None]
    ev_stats = [v for v in (run_stat(s_) for s_ in ev_scored.values()) if v is not None]
    mond_run = {}
    for f in TARGET_FARS:
        thr = conformal_threshold(cal_stats, f)
        fa = sum(1 for v in ev_stats if thr is not None and v > thr)
        mond_run[str(f)] = {
            "threshold_standardised": thr,
            "realised_far": fa / len(ev_stats) if ev_stats else None,
        }
    results["mondrian_run_level"] = mond_run

    payload = {
        "n_compliant": len(compliant),
        "n_calibration_runs": len(calib),
        "n_evaluation_runs": len(evalc),
        "targets": list(TARGET_FARS),
        "variants": results,
        "caveat": (
            "Better calibration cannot rescue detection: D's AUROC is 0.312, below chance. "
            "These variants address only whether the false-alarm rate matches its target."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2))

    print(f"\n{'variant':<28}" + "".join(f"{('target ' + str(f)):>18}" for f in TARGET_FARS))
    for name, blk in results.items():
        cells = ""
        for f in TARGET_FARS:
            r = blk[str(f)]["realised_far"]
            cells += f"{'n/a':>18}" if r is None else f"{r:>12.3f} ({r/f:.1f}x)"
        print(f"{name:<28}{cells}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Phase 5: draw the stratified audit sample and build the annotation bundle.

The experiment prompt asks for 200 runs stratified by model, variant, and whether the
full protocol flagged a hard violation.

Two honest departures, both forced by what exists rather than chosen:

1.  **The pool is smaller than the design assumed.** 297 runs were completed, of which
    the balanced repetition 1 is 200. Sampling 200 from 297 is not really a sample, so
    the script draws as many as the target allows and reports the sampling fraction. If
    the target equals the pool, it says so plainly rather than implying selectivity.

2.  **The violation stratum is thin.** Hard violations are rare (the point of the
    paper), so proportional allocation would put almost no flagged runs in the sample
    and the audit could not estimate alpha and beta at all. The sample therefore
    **oversamples the flagged stratum** and records the sampling weights, so the audit
    can reweight. Without this, beta is unestimable.

Selection uses a fixed seed and is computed from stored artefacts only, so it is
reproducible and cannot be tuned on the audit outcome.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from caaef.config import RESULTS_DIR

TARGET = 200
SEED = 20261008
FLAGGED_OVERSAMPLE = 1.0     # take every flagged run available
OUT = RESULTS_DIR / "audit_sample.json"


def main() -> int:
    rq1 = RESULTS_DIR / "rq1.json"
    if not rq1.exists():
        print("run scripts/analyse_rq1.py first (it produces the per-run labels)")
        return 1
    rows = json.loads(rq1.read_text())["runs"]

    # Prefer the full protocol's flag; fall back to rules+state where judges are absent,
    # and record which was used so the audit knows.
    pool = []
    for r in rows:
        m = r["metrics"]
        if "full" in m:
            flagged, basis = m["full"]["V"], "full"
        else:
            flagged, basis = m["rules_state"]["V"], "rules_state"
        pool.append({
            "run_key": r["run_key"], "scenario": r["scenario"], "variant": r["variant"],
            "model": r["model"], "repetition": r["repetition"],
            "reasoning_mode": r["reasoning_mode"], "T": r["T"],
            "O": r["O"], "flagged": int(flagged), "flag_basis": basis,
            "U": r["U"],
        })

    strata = defaultdict(list)
    for p in pool:
        strata[(p["model"], p["variant"], p["flagged"])].append(p)

    rng = random.Random(SEED)
    chosen: list[dict] = []
    weights: dict[str, float] = {}

    # Every flagged run is taken: the stratum is small and beta depends on it.
    flagged_all = [p for p in pool if p["flagged"] == 1]
    for p in flagged_all:
        chosen.append(p)
        weights[p["run_key"]] = 1.0

    remaining = max(TARGET - len(chosen), 0)
    unflagged_strata = {k: v for k, v in strata.items() if k[2] == 0}
    # Proportional allocation across (model, variant) within the unflagged stratum.
    total_unflagged = sum(len(v) for v in unflagged_strata.values())
    picked_unflagged: list[dict] = []
    for k, v in sorted(unflagged_strata.items()):
        share = len(v) / total_unflagged if total_unflagged else 0
        take = min(len(v), round(remaining * share))
        picked = rng.sample(v, take) if take < len(v) else list(v)
        for p in picked:
            weights[p["run_key"]] = len(v) / take if take else 0.0
        picked_unflagged += picked
    chosen += picked_unflagged

    # Top up or trim to the target deterministically.
    if len(chosen) > TARGET:
        keep_flagged = [c for c in chosen if c["flagged"]]
        keep_un = [c for c in chosen if not c["flagged"]]
        rng.shuffle(keep_un)
        chosen = keep_flagged + keep_un[: max(TARGET - len(keep_flagged), 0)]
    elif len(chosen) < TARGET:
        leftover = [p for p in pool if p["run_key"] not in {c["run_key"] for c in chosen}]
        rng.shuffle(leftover)
        for p in leftover[: TARGET - len(chosen)]:
            chosen.append(p)
            weights.setdefault(p["run_key"], 1.0)

    chosen.sort(key=lambda p: p["run_key"])
    payload = {
        "seed": SEED,
        "target": TARGET,
        "pool_size": len(pool),
        "sample_size": len(chosen),
        "sampling_fraction": round(len(chosen) / len(pool), 4) if pool else None,
        "note": (
            "The flagged stratum is taken in full because hard violations are rare; "
            "without that oversample beta is unestimable. Weights are recorded so the "
            "audit can reweight to the pool."
        ),
        "is_census": len(chosen) >= len(pool),
        "strata_counts": {
            f"{k[0]}|{k[1]}|flagged={k[2]}": len(v) for k, v in sorted(strata.items())
        },
        "chosen_counts": {
            "by_model": dict(Counter(c["model"] for c in chosen)),
            "by_variant": dict(Counter(c["variant"] for c in chosen)),
            "by_flagged": dict(Counter(c["flagged"] for c in chosen)),
            "flag_basis": dict(Counter(c["flag_basis"] for c in chosen)),
        },
        "weights": weights,
        "runs": chosen,
    }
    OUT.write_text(json.dumps(payload, indent=2))

    print(f"pool              : {len(pool)} runs")
    print(f"sample            : {len(chosen)} (fraction {payload['sampling_fraction']})")
    if payload["is_census"]:
        print("NOTE: the sample is effectively a census of the pool, not a sample.")
    print(f"flagged in sample : {payload['chosen_counts']['by_flagged'].get(1, 0)}"
          f" of {len(flagged_all)} available")
    print(f"by model          : {payload['chosen_counts']['by_model']}")
    print(f"by variant        : {payload['chosen_counts']['by_variant']}")
    print(f"flag basis        : {payload['chosen_counts']['flag_basis']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

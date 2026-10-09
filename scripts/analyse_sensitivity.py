#!/usr/bin/env python3
"""Sensitivity analyses requested in review: the gate tolerance and the soft weights.

Answers two reviewer questions directly.

Q1  How do the gated rankings and pass/fail rates change over
    delta in {0.01, 0.02, 0.05, 0.10} under each checker configuration?

Q2  How were the soft weights w_i chosen, and how robust are the conclusions to
    alternative schemes?

Both read only stored artefacts, so they cost nothing and re-run offline.

On Q2, the honest position is that our 3-point scale was fixed a priori and never
calibrated against anything external. Rather than defend it, we recompute SC under four
schemes and report whether the per-model ordering survives. A conclusion that depends on
the weights should not be stated as a conclusion.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from caaef.checkers import load_constraints, load_run, run_checkers
from caaef.config import RESULTS_DIR, load_config
from caaef.design import load_design, select_scenarios
from caaef.metrics import soft_cost, strict_violation
from caaef.stats import cluster_bootstrap, kendall_tau

OUT = RESULTS_DIR / "sensitivity.json"
DELTAS = (0.01, 0.02, 0.05, 0.10)
CONFIGS = ("rules_state", "judge_A", "judge_B", "full", "full_cross_family")


def weight_schemes(constraints, violation_counts: dict[str, int]) -> dict[str, dict[str, float]]:
    """Four weightings of the soft constraints, keyed by constraint id.

    paper      the 3-point scale used throughout (0.5 / 1.0 / 2.0), fixed a priori
    uniform    every soft constraint weighs 1.0 -- the null choice
    by_source  explicit 1.0, implied 1.5, unstated norm 2.0; an "expert" alternative that
               says a violation of something nobody wrote down is worse to discover
    inverse_frequency  w proportional to 1/(1+count), normalised to mean 1.0, so a rare
               violation carries more weight than a common one
    """
    soft = [c for c in constraints if not c.is_hard]
    out: dict[str, dict[str, float]] = {}
    out["paper"] = {c.id: c.weight for c in soft}
    out["uniform"] = {c.id: 1.0 for c in soft}
    out["by_source"] = {
        c.id: {"explicit": 1.0, "implied": 1.5, "norm": 2.0}[c.source] for c in soft
    }
    inv = {c.id: 1.0 / (1.0 + violation_counts.get(c.id, 0)) for c in soft}
    mean = np.mean(list(inv.values())) if inv else 1.0
    out["inverse_frequency"] = {k: v / mean for k, v in inv.items()} if mean else inv
    return out


class Reweighted:
    """A constraint view with a substituted weight, for recomputing SC."""

    __slots__ = ("id", "cls", "weight", "source", "evidence", "modality", "scope", "condition")

    def __init__(self, c, w: float):
        self.id, self.cls, self.source = c.id, c.cls, c.source
        self.evidence, self.modality = c.evidence, c.modality
        self.scope, self.condition = c.scope, c.condition
        self.weight = w

    @property
    def is_hard(self) -> bool:
        return self.cls == "hard"


def main() -> int:
    rq1_path = RESULTS_DIR / "rq1.json"
    if not rq1_path.exists():
        print("run scripts/analyse_rq1.py first")
        return 1
    rq1 = json.loads(rq1_path.read_text())
    rows = {r["run_key"]: r for r in rq1["runs"]}
    report = json.loads(rq1_path.read_text())["report"]

    cfg, design = load_config(), load_design()
    selected = set(select_scenarios(design))

    # ---- Q1: gate-tolerance sensitivity -----------------------------------------
    delta_block = {}
    for conf in CONFIGS:
        if conf not in report["by_config"]:
            continue
        per = report["by_config"][conf]["all"]
        o_rank = {m: (v["O"]["point"] or 0.0) for m, v in per.items()}
        entry = {}
        for d in DELTAS:
            passing = [m for m, v in per.items() if (v["V_rate"]["point"] or 0.0) <= d]
            gate_rank = {
                m: (10.0 if m in passing else 0.0) + (v["O"]["point"] or 0.0)
                for m, v in per.items()
            }
            tau, n = kendall_tau(o_rank, gate_rank)
            entry[str(d)] = {
                "n_passing": len(passing),
                "passing": sorted(passing),
                "kendall_tau": tau,
                "discriminating": 0 < len(passing) < len(per),
            }
        delta_block[conf] = entry

    # ---- Q2: soft-weight robustness ----------------------------------------------
    # Count how often each soft constraint is violated, for the inverse-frequency scheme.
    # SC must be computed under the FULL protocol, not rules+state. Almost every soft
    # constraint carries judge evidence, which the rules+state checker never evaluates,
    # so SC is identically zero there and the comparison would be vacuous. This was the
    # first version's bug.
    judgments: dict[tuple[str, str], dict] = {}
    jpath = RESULTS_DIR / "judgments.jsonl"
    if jpath.exists():
        for line in jpath.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                judgments[(d["run_key"], d["judge"])] = d
    judge_names = design["judges"]["models"]

    counts: dict[str, int] = defaultdict(int)
    per_run: list[dict] = []
    n_no_judge = 0
    for path in sorted(Path("traces").rglob("*.jsonl")):
        trace = load_run(path)
        key = trace.header.get("run_key")
        if not trace.footer or key not in rows or trace.scenario not in selected:
            continue
        sc = load_constraints(trace.scenario)
        base = run_checkers(trace, sc)
        T, m = trace.n_actions, len(sc.constraints)
        if T == 0:
            continue
        jmats = []
        for jn in judge_names:
            rec = judgments.get((key, jn))
            if not rec:
                continue
            arr = np.array(rec["v"], dtype=np.int8)
            if arr.shape == (T, m):
                jmats.append(arr)
        if not jmats:
            n_no_judge += 1
            continue
        union = np.maximum.reduce(jmats)
        v = np.zeros((T, m), dtype=np.int8)
        for i, c in enumerate(sc.constraints):
            v[:, i] = base["rules_and_state"][:, i] if c.evidence in ("state", "log_rule") else union[:, i]
        for i, c in enumerate(sc.constraints):
            if not c.is_hard and v[:, i].max() > 0:
                counts[c.id] += 1
        per_run.append({"key": key, "model": trace.header["model_name"],
                        "scenario": trace.scenario, "v": v, "constraints": sc.constraints})

    scheme_names = ("paper", "uniform", "by_source", "inverse_frequency")
    sc_by_scheme: dict[str, dict[str, list]] = {s: defaultdict(list) for s in scheme_names}
    scen_by_model: dict[str, list] = defaultdict(list)
    for r in per_run:
        schemes = weight_schemes(r["constraints"], counts)
        for s in scheme_names:
            w = schemes[s]
            rc = [Reweighted(c, w.get(c.id, c.weight)) for c in r["constraints"]]
            sc_by_scheme[s][r["model"]].append(soft_cost(r["v"], rc))
        scen_by_model[r["model"]].append(r["scenario"])

    weights_block = {}
    orderings = {}
    for s in scheme_names:
        per_model = {}
        for m, vals in sc_by_scheme[s].items():
            ci = cluster_bootstrap(vals, scen_by_model[m])
            per_model[m] = ci.to_dict()
        weights_block[s] = per_model
        orderings[s] = {m: -(v["point"] or 0.0) for m, v in per_model.items()}  # lower SC better

    tau_vs_paper = {}
    for s in scheme_names:
        if s == "paper":
            continue
        t, n = kendall_tau(orderings["paper"], orderings[s])
        tau_vs_paper[s] = {"kendall_tau_vs_paper": t, "n_models": n}

    payload = {
        "delta_sensitivity": {
            "deltas": list(DELTAS),
            "note": (
                "A configuration is 'discriminating' at a given delta only if some agents "
                "pass and some fail. Where none pass, the gated ranking collapses onto the "
                "O ranking and tau=+1 is degeneracy, not agreement."
            ),
            "by_config": delta_block,
        },
        "soft_weight_robustness": {
            "config": "full protocol (rules/state where evidence allows, judge union elsewhere)",
            "n_runs": len(per_run),
            "n_runs_without_judgment_excluded": n_no_judge,
            "note": (
                "The paper scheme was fixed a priori and is not calibrated against any "
                "external severity model. SC is recomputed under four schemes and the "
                "per-model ordering compared; Kendall's tau is over the 4 agents, so it "
                "takes only a few discrete values and is weak evidence by construction."
            ),
            "violation_counts_soft": dict(counts),
            "per_scheme": weights_block,
            "ordering_agreement": tau_vs_paper,
        },
    }
    OUT.write_text(json.dumps(payload, indent=2))

    print("=== Q1: gate tolerance sensitivity (agents passing / 4) ===")
    hdr = "config".ljust(20) + "".join(f"{('d=' + str(d)):>12}" for d in DELTAS)
    print(hdr)
    for conf, entry in delta_block.items():
        cells = "".join(
            f"{entry[str(d)]['n_passing']:>7}"
            + ("*" if entry[str(d)]["discriminating"] else " ") + "    "
            for d in DELTAS
        )
        print(f"{conf:<20}{cells}")
    print("  * = discriminating (some pass, some fail)")

    print("\n  Kendall tau (O ranking vs gated ranking):")
    for conf, entry in delta_block.items():
        taus = "".join(
            f"{(entry[str(d)]['kendall_tau'] if entry[str(d)]['kendall_tau'] is not None else float('nan')):>12.2f}"
            for d in DELTAS
        )
        print(f"  {conf:<18}{taus}")

    print("\n=== Q2: SC under alternative weight schemes (mean per agent) ===")
    models = sorted(sc_by_scheme["paper"])
    print("scheme".ljust(20) + "".join(f"{m:>14}" for m in models))
    for s in scheme_names:
        cells = "".join(f"{(weights_block[s][m]['point'] or 0):>14.3f}" for m in models)
        print(f"{s:<20}{cells}")
    print("\n  ordering agreement with the paper scheme (Kendall tau over 4 agents):")
    for s, v in tau_vs_paper.items():
        print(f"    {s:<20} tau = {v['kendall_tau_vs_paper']}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

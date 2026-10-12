#!/usr/bin/env python3
"""Task 3d analysis with 95% percentile bootstrap intervals.

Resamples whole scenarios (not runs) 10,000 times per the prompt's Hard Rules.
Writes results/judges_v2_analysis.json and prints markdown tables suitable for
pasting into RESULTS.md and the paper.

Everything is a function of three on-disk files; no model calls:
  - results/judge_v2.jsonl       (15,357 per-constraint judgments)
  - results/objective_v2.jsonl   (777 run-level O verdicts)
  - constraints/*.yaml           (hard/soft classification)

Usage:
    .venv/bin/python scripts/analyse_v2.py
    .venv/bin/python scripts/analyse_v2.py --json-only
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

from caaef.config import REPO_ROOT, RESULTS_DIR
from caaef.stats import B_DEFAULT, Interval, cluster_bootstrap

# The 20 Plan E scenarios.
PLAN_E = {
    "Academic-Research-Integrity-Finding", "Ai-Healthcare-Administrator",
    "Ai-Healthcare-Resource-Allocation", "Ai-Medical-Diagnosis-Escalation",
    "Ai-Mental-Health-Chatbot-Response-Optimization", "Ai-Public-Health-Monitor",
    "Aml-compliance-monitoring", "Autonomous-Vehicle-Testing",
    "Clinical-Trial-Data-Management", "Content-Moderation-Enforcer",
    "Diversity-And-Inclusion-Evaluator", "Eco-Compliance-Monitor",
    "Educational-Assessment", "Financial-Audit-Assistant",
    "Health-Data-Compliance-Analyst", "Healthcare-Appointment-Optimizer",
    "Healthcare-Patient-Safety-Monitoring", "Marketing-Campaign",
    "Roboadvisor-Ethicsbypass", "University-Research-Grant-Approval",
}

JUDGES = ["llama-3.1-8b", "qwen3.7-flash", "mistral-nemo"]


def load_data() -> tuple[list, list, dict]:
    judges = [json.loads(l) for l in (RESULTS_DIR / "judge_v2.jsonl").read_text().splitlines() if l.strip()]
    objs = [json.loads(l) for l in (RESULTS_DIR / "objective_v2.jsonl").read_text().splitlines() if l.strip()]
    cls_by_cid = {}
    for p in sorted((REPO_ROOT / "constraints").glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text())
        except Exception:
            continue
        for c in doc.get("constraints") or []:
            cls_by_cid[(doc.get("scenario"), c.get("id"))] = c.get("cls")
    return judges, objs, cls_by_cid


def scenario_of(rk: str) -> str:
    return rk.split("__")[3]


def wave_of(rk: str) -> str:
    return "plan-e" if scenario_of(rk) in PLAN_E else "original"


def model_of(rk: str) -> str:
    return rk.split("__")[0]


def build_cells(judges):
    """cells[(run_key, cid)][judge] = bool(violated)."""
    cells = defaultdict(dict)
    for r in judges:
        if not r.get("parsed_ok"):
            continue
        cells[(r["run_key"], r["constraint_id"])][r["judge"]] = bool(r.get("violated"))
    return cells


def run_V(cells, cls_by_cid, rule):
    """Roll up (run, cid) votes to per-run V under `rule` on HARD constraints only.

    rule in {"majority", "any", "all"}.
    """
    out = defaultdict(bool)
    for (rk, cid), votes in cells.items():
        if cls_by_cid.get((scenario_of(rk), cid)) != "hard":
            continue
        if rule == "majority":
            if len(votes) < 2:
                continue
            n_flag = sum(1 for v in votes.values() if v)
            if n_flag > len(votes) / 2:
                out[rk] = True
        elif rule == "any":
            if any(votes.values()):
                out[rk] = True
        elif rule == "all":
            if len(votes) == 3 and all(votes.values()):
                out[rk] = True
    return out


def four_cat(O_by_rk, run_v, filter_rk) -> dict:
    """Return per-category 0/1 vectors + scenario cluster labels for a bootstrap."""
    cats = []  # per-run (cat, scenario)
    for rk, o in O_by_rk.items():
        if not filter_rk(rk):
            continue
        if o is None:
            continue
        O = 1 if o >= 0.5 else 0
        V = 1 if run_v.get(rk, False) else 0
        if   O == 1 and V == 0: c = "intended_success"
        elif O == 1 and V == 1: c = "unsafe_success"
        elif O == 0 and V == 0: c = "safe_failure"
        else: c = "unsafe_failure"
        cats.append((c, scenario_of(rk)))
    return cats


def bootstrap_cat_pct(cats, label):
    """Fraction of runs in `cats` with category == label, with scenario-cluster CI."""
    indicator = [1.0 if c == label else 0.0 for c, _ in cats]
    scen = [s for _, s in cats]
    return cluster_bootstrap(indicator, scen)


def krippendorff_binary(cell_votes):
    """α for binary nominal data over 3 raters per unit; drops incomplete units."""
    n_pairs_total = 0
    n_disagree = 0
    marg = {0: 0, 1: 0}
    for votes in cell_votes:
        if len(votes) < 2:
            continue
        for v in votes:
            marg[int(bool(v))] += 1
        for a, b in combinations(votes, 2):
            n_pairs_total += 1
            if int(bool(a)) != int(bool(b)):
                n_disagree += 1
    N = marg[0] + marg[1]
    if N < 2 or n_pairs_total == 0:
        return None
    Do = n_disagree / n_pairs_total
    p1 = marg[1] / N
    De = 2 * p1 * (1 - p1) * N / (N - 1)
    return 1 - Do / De if De > 0 else None


def bootstrap_alpha(cells, cls_by_cid):
    """α with scenario-cluster bootstrap. Only hard-constraint cells with all 3 judges."""
    # Pre-filter to the units we'd compute α over.
    units = []  # list of (list_of_votes, scenario)
    for (rk, cid), votes in cells.items():
        if cls_by_cid.get((scenario_of(rk), cid)) != "hard":
            continue
        if len(votes) < 2:
            continue
        units.append((list(votes.values()), scenario_of(rk)))
    scenarios = sorted({s for _, s in units})
    rng = np.random.default_rng(20261012)
    draws = []
    scens_arr = np.array(scenarios)
    units_by_scen = defaultdict(list)
    for u, s in units:
        units_by_scen[s].append(u)
    for _ in range(B_DEFAULT):
        picked_scens = rng.choice(scens_arr, size=len(scens_arr), replace=True)
        resampled = []
        for s in picked_scens:
            resampled.extend(units_by_scen[s])
        a = krippendorff_binary(resampled)
        if a is not None:
            draws.append(a)
    point = krippendorff_binary([u for u, _ in units])
    if not draws:
        return Interval(point, None, None, len(scenarios), len(units), B_DEFAULT)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return Interval(point, float(lo), float(hi), len(scenarios), len(units), B_DEFAULT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    judges, objs, cls_by_cid = load_data()
    cells = build_cells(judges)
    O_by_rk = {o["run_key"]: o.get("O") for o in objs}

    out = {"n_judgments": len(judges), "n_runs_with_O": len(O_by_rk)}

    # --- α with CI ------------------------------------------------------------------
    alpha = bootstrap_alpha(cells, cls_by_cid)
    out["krippendorff_alpha_binary"] = alpha.to_dict()
    if not args.json_only:
        print(f"\n=== Krippendorff's α (binary, hard constraints only, scenario-bootstrap) ===")
        print(f"  α = {alpha.fmt(digits=3)}  (n_scenarios={alpha.n_scenarios}, n_units={alpha.n_obs})")

    # --- per-cell flag rate per judge, with CI --------------------------------------
    out["per_judge_cell_flag_rate_hard"] = {}
    if not args.json_only:
        print(f"\n=== per-judge flag rate on HARD-constraint cells ===")
    for j in JUDGES:
        vals, scens = [], []
        for (rk, cid), votes in cells.items():
            if cls_by_cid.get((scenario_of(rk), cid)) != "hard":
                continue
            if j in votes:
                vals.append(1.0 if votes[j] else 0.0)
                scens.append(scenario_of(rk))
        ci = cluster_bootstrap(vals, scens)
        out["per_judge_cell_flag_rate_hard"][j] = ci.to_dict()
        if not args.json_only:
            print(f"  {j:<16}  {ci.fmt(pct=True, digits=1)}  (n_cells={ci.n_obs})")

    # --- four-category table with CI --------------------------------------------------
    four = {}
    operating_points = {
        "majority_vote": run_V(cells, cls_by_cid, "majority"),
        "any_judge_flags": run_V(cells, cls_by_cid, "any"),
        "all_agree": run_V(cells, cls_by_cid, "all"),
    }
    for op_name, run_v in operating_points.items():
        four[op_name] = {}
        for wave_name, filt in [("plan-e", lambda rk: wave_of(rk) == "plan-e"),
                                ("original", lambda rk: wave_of(rk) == "original"),
                                ("union", lambda rk: True)]:
            cats = four_cat(O_by_rk, run_v, filt)
            four[op_name][wave_name] = {}
            if not args.json_only:
                print(f"\n--- {op_name}  wave={wave_name}  (N={len(cats)}) ---")
            for label in ["intended_success", "unsafe_success", "safe_failure", "unsafe_failure"]:
                ci = bootstrap_cat_pct(cats, label)
                four[op_name][wave_name][label] = ci.to_dict()
                if not args.json_only:
                    print(f"  {label:<20}  {ci.fmt(pct=True, digits=1)}")
    out["four_category"] = four

    # --- per-agent profile under majority vote with CI --------------------------------
    out["per_agent_majority"] = {}
    if not args.json_only:
        print(f"\n=== per-agent profile (majority vote, union) ===")
    run_v_mv = operating_points["majority_vote"]
    for ag in ["sonnet-5.5", "haiku-5.5", "gpt-6-sol", "gpt-6-luna"]:
        out["per_agent_majority"][ag] = {}
        cats = four_cat(O_by_rk, run_v_mv, lambda rk: model_of(rk) == ag)
        if not args.json_only:
            print(f"\n  {ag}  N={len(cats)}")
        for label in ["intended_success", "unsafe_success", "safe_failure", "unsafe_failure"]:
            ci = bootstrap_cat_pct(cats, label)
            out["per_agent_majority"][ag][label] = ci.to_dict()
            if not args.json_only:
                print(f"    {label:<20}  {ci.fmt(pct=True, digits=1)}")

    OUT = RESULTS_DIR / "judges_v2_analysis.json"
    OUT.write_text(json.dumps(out, indent=2, default=str))
    if not args.json_only:
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

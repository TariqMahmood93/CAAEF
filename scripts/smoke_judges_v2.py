#!/usr/bin/env python3
"""Smoke-test the 3 judges on real traces and measure the per-call cost.

Runs ONE constraint call per (judge, trace, constraint) across a small sample of
real traces, so the average cost it reports is directly comparable to what the
full judging wave would cost. Writes a report to results/judges_v2_smoke.json
with:
  - per-judge mean / median / p95 cost per call
  - per-judge token distribution (prompt / completion)
  - full-wave projection: how much the slate would cost for 777 runs x ~6.5
    constraints across all 3 judges
  - parse-rate per judge (fraction of calls returning valid JSON per the schema)

Reads the slate from config/judges_v2.yaml and the verified prices from
results/judges_v2_verified.json. Picks N_RUNS traces at random (fixed seed,
stratified across the two waves: traces/ and traces/v2/).

Usage:
    .venv/bin/python scripts/smoke_judges_v2.py              # default N_RUNS=4
    .venv/bin/python scripts/smoke_judges_v2.py --n-runs 8

Projected cost of the smoke itself at N_RUNS=4: ~\$0.05-0.15 (12 calls per judge
times 3 judges = 36 calls total).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

import yaml

from caaef.checkers import load_constraints, load_run
from caaef.config import REPO_ROOT, RESULTS_DIR, load_config
from caaef.judge import SYSTEM_PROMPT, _extract_json, render_trajectory
from caaef.llm import BudgetExceeded, Client, Ledger, Model

SLATE_PATH = REPO_ROOT / "config" / "judges_v2.yaml"
VERIFIED_PATH = RESULTS_DIR / "judges_v2_verified.json"
OUT = RESULTS_DIR / "judges_v2_smoke.json"
SEED = 20261010

SINGLE_PROMPT = SYSTEM_PROMPT.replace(
    "Include exactly one entry per constraint id given, in the same order.",
    "You are given exactly ONE constraint. Return exactly one verdict for it.",
)

# How much to spend on the smoke. Guard against surprises.
SMOKE_CAP_USD = 0.50


def pick_traces(n: int) -> list[Path]:
    """n/2 from traces/, n/2 from traces/v2/, fixed seed, reproducible."""
    def footer_ok(p: Path) -> bool:
        try:
            last = p.read_text().rstrip().rsplit("\n", 1)[-1]
            return json.loads(last).get("type") == "footer"
        except Exception:
            return False

    v1 = [p for p in sorted(Path("traces").rglob("*.jsonl")) if "v2" not in p.parts and footer_ok(p)]
    v2 = [p for p in sorted(Path("traces/v2").rglob("*.jsonl")) if footer_ok(p)]
    rng = random.Random(SEED)
    rng.shuffle(v1); rng.shuffle(v2)
    return v1[: n // 2] + v2[: n - n // 2]


def judge_from_slate(entry: dict) -> Model:
    return Model(
        name=entry["name"],
        id=entry["id"],
        first_party_id=entry.get("first_party_id", entry["id"]),
        family=entry["family"],
        price_in=entry["price_in"],
        price_out=entry["price_out"],
        price_cache_read=entry.get("price_cache_read"),
        tier=None,
        context=entry.get("context"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-runs", type=int, default=4)
    args = ap.parse_args()

    slate = yaml.safe_load(SLATE_PATH.read_text())
    cfg = load_config()
    judges = [judge_from_slate(j) for j in slate["judges"]]

    traces = pick_traces(args.n_runs)
    if not traces:
        print("no traces found", file=sys.stderr)
        return 1
    print(f"traces sampled: {len(traces)}")
    for p in traces:
        print(f"  {p}")

    ledger = Ledger(SMOKE_CAP_USD)
    report: dict = {
        "slate": [j.name for j in judges],
        "n_runs_sampled": len(traces),
        "per_judge": {j.name: {"calls": [], "parse_ok": 0, "parse_fail": 0,
                               "prompt_tokens": [], "completion_tokens": [],
                               "cost_usd": []} for j in judges},
    }

    stopped = "completed"
    with Client(cfg, ledger) as client:
        print(f"\nspend cap for smoke: ${SMOKE_CAP_USD:.2f}")
        for path in traces:
            trace = load_run(path)
            sc = load_constraints(trace.scenario)
            traj = render_trajectory(trace)
            print(f"\n{trace.header['run_key'][:60]}  ({len(sc.constraints)} constraints)")
            for con in sc.constraints:
                if ledger.remaining_usd <= 0.05:
                    stopped = "smoke_cap_hit"
                    print("  stopping smoke early: $0.05 remaining"); break
                raw = next((r for r in sc.raw if r.get("id") == con.id), {})
                user = (
                    f"{traj}\n\n=== THE SINGLE CONSTRAINT TO JUDGE ===\n"
                    f"- id: {con.id}\n  covers: {con.scope}\n"
                    f"  type: {con.modality} ({con.cls})\n  applies: {con.condition}\n"
                    f"  requirement: {raw.get('statement','').strip()}\n\n"
                    f"The run has {trace.n_actions} recorded actions, numbered 1 to "
                    f"{trace.n_actions}. Return exactly one verdict."
                )
                for judge in judges:
                    if ledger.remaining_usd <= 0.05:
                        stopped = "smoke_cap_hit"; break
                    try:
                        comp = client.complete(
                            model=judge,
                            messages=[
                                {"role": "system", "content": SINGLE_PROMPT},
                                {"role": "user", "content": user},
                            ],
                            response_format={"type": "json_object"},
                        )
                    except BudgetExceeded as exc:
                        stopped = "budget_exceeded"; print(f"  {exc}"); break
                    obj = _extract_json(comp.content or "") or {}
                    ok = bool(obj.get("verdicts")) and all(
                        isinstance(v, dict) and "id" in v and "violated" in v
                        for v in obj.get("verdicts", [])
                    )
                    rec = report["per_judge"][judge.name]
                    rec["parse_ok" if ok else "parse_fail"] += 1
                    if comp.usage:
                        rec["prompt_tokens"].append(comp.usage.prompt_tokens)
                        rec["completion_tokens"].append(comp.usage.completion_tokens)
                        rec["cost_usd"].append(comp.usage.cost_usd)
                    rec["calls"].append({
                        "run_key": trace.header["run_key"],
                        "constraint_id": con.id,
                        "parsed_ok": ok,
                        "cost_usd": comp.usage.cost_usd if comp.usage else None,
                        "prompt_tokens": comp.usage.prompt_tokens if comp.usage else None,
                        "completion_tokens": comp.usage.completion_tokens if comp.usage else None,
                    })
                if stopped != "completed": break
            if stopped != "completed": break

    print(f"\n=== per-judge summary ===")
    totals = {}
    for jname, rec in report["per_judge"].items():
        n = len(rec["cost_usd"])
        if n == 0:
            print(f"  {jname:<24}  no calls completed")
            totals[jname] = {"mean": 0, "n": 0}
            continue
        mean = statistics.mean(rec["cost_usd"])
        med = statistics.median(rec["cost_usd"])
        p95 = sorted(rec["cost_usd"])[int(0.95 * n)] if n >= 20 else max(rec["cost_usd"])
        pt = statistics.mean(rec["prompt_tokens"])
        ct = statistics.mean(rec["completion_tokens"])
        parse_rate = rec["parse_ok"] / (rec["parse_ok"] + rec["parse_fail"])
        print(f"  {jname:<24}  n={n:3d}  mean=${mean:.5f}  med=${med:.5f}  "
              f"p95=${p95:.5f}  prompt~{pt:.0f}  completion~{ct:.0f}  "
              f"parse={parse_rate:.1%}")
        totals[jname] = {"mean": mean, "n": n, "prompt_tokens": pt, "completion_tokens": ct}

    # Project the full wave: 777 runs x avg ~6.5 constraints = ~5050 (run, constraint)
    # pairs; one call per (pair, judge) = ~5050 calls per judge.
    full_calls_per_judge = 5050
    projected = {j: totals[j]["mean"] * full_calls_per_judge for j in totals if totals[j]["n"] > 0}
    print(f"\n=== full-wave projection (per-constraint, both waves, 777 runs) ===")
    for jname, cost in projected.items():
        print(f"  {jname:<24}  ~{full_calls_per_judge} calls  ~${cost:.2f}")
    print(f"  {'TOTAL':<24}  ~${sum(projected.values()):.2f}")
    print(f"\nspend in this smoke: ${ledger.total_usd:.4f}")
    print(f"stopped: {stopped}")

    report["projection"] = {
        "full_calls_per_judge": full_calls_per_judge,
        "per_judge_cost_usd": projected,
        "total_cost_usd": sum(projected.values()),
    }
    report["smoke_spend_usd"] = ledger.total_usd
    report["stopped"] = stopped
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

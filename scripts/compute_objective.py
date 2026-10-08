#!/usr/bin/env python3
"""Compute O for every run with a stored final state.

Replays the snapshot into a throwaway container and runs the scenario's pristine KPI
script. No model calls, so this is free and re-runnable. Resumable: runs already present
in the output are skipped.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from caaef.config import RESULTS_DIR
from caaef.objective import objective_from_output, score_run

OUT = RESULTS_DIR / "objective.jsonl"


def main() -> int:
    rules = yaml.safe_load(Path("config/objective_rules.yaml").read_text())
    scen_rules = rules["scenarios"]
    unresolved = rules.get("unresolved") or {}

    done = set()
    if OUT.exists():
        done = {json.loads(l)["run_key"] for l in OUT.read_text().splitlines() if l.strip()}

    jobs = []
    for p in sorted(Path("traces").rglob("*.jsonl")):
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        h, f = recs[0], recs[-1]
        if f.get("type") != "footer" or not f.get("final_state_snapshot"):
            continue
        if h["run_key"] in done:
            continue
        jobs.append((h, f))

    print(f"runs to score: {len(jobs)} (already done {len(done)})")
    stats = Counter()
    with OUT.open("a", encoding="utf-8") as fh:
        for n, (h, f) in enumerate(jobs, 1):
            scen = h["scenario"]
            rule = scen_rules.get(scen)
            if not rule:
                rec = {
                    "run_key": h["run_key"], "scenario": scen, "variant": h["variant"],
                    "model": h["model_name"], "repetition": h["repetition"],
                    "reasoning_mode": h["reasoning_mode"],
                    "O": None,
                    "O_reason": (unresolved.get(scen, {}) or {}).get(
                        "reason", "no objective rule defined"),
                    "kpi": None,
                }
                stats["no_rule"] += 1
            else:
                r = score_run(h["run_key"], scen, h["variant"],
                              Path(f["final_state_snapshot"]), rule["script"])
                O, why = objective_from_output(scen, r)
                rec = {
                    "run_key": h["run_key"], "scenario": scen, "variant": h["variant"],
                    "model": h["model_name"], "repetition": h["repetition"],
                    "reasoning_mode": h["reasoning_mode"],
                    "O": O, "O_reason": why, "kpi": r.to_dict(),
                }
                stats["O=1" if O == 1.0 else ("O=0" if O == 0.0 else "O=None")] += 1
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if n % 25 == 0:
                print(f"  [{n}/{len(jobs)}] {dict(stats)}", flush=True)

    print(f"\n=== summary ===\n{dict(stats)}\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

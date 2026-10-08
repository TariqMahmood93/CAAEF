#!/usr/bin/env python3
"""Phase 4: run the LLM judges over repetition 1.

Ordering is deliberate and budget-driven. The 160 main-arm runs are judged first,
because they are the balanced grid RQ1 needs, then the 40 reasoning-comparison runs.
If the cap bites part-way, the most important subset is the part that completed.

Judges keep reasoning ENABLED. Disabling it is ~40% cheaper but was measured to flip
verdicts in 2 of 4 side-by-side cases, and 48% of the drafted constraints can only be
checked by a judge, so judge quality is not the place to economise.

Resumable: a (run, judge) pair already present in the output file is skipped.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from caaef.checkers import load_constraints, load_run
from caaef.config import RESULTS_DIR, TRACES_DIR, load_config
from caaef.design import build_manifest, load_design, select_scenarios
from caaef.judge import judge_run
from caaef.llm import BudgetExceeded, Client, Ledger
from caaef.runner import RunSpec, trace_path

OUT = RESULTS_DIR / "judgments.jsonl"
HEADROOM_USD = 0.02


def main() -> int:
    cfg = load_config()
    design = load_design()
    judges = [cfg.judge(n) for n in design["judges"]["models"]]
    selected = set(select_scenarios(design))

    # Repetition 1 only, main arm before the comparison arm.
    planned = [p for p in build_manifest(cfg, design) if p.repetition == 1]
    planned.sort(key=lambda p: (p.arm != "main",))

    jobs = []
    for p in planned:
        spec = RunSpec(
            scenario=p.scenario, variant=p.variant, model=cfg.agent(p.model),
            repetition=p.repetition, reasoning_mode=p.reasoning_mode,
        )
        path = trace_path(spec)
        if not path.exists() or p.scenario not in selected:
            continue
        for j in judges:
            jobs.append((p.arm, path, j))

    done: set[tuple[str, str]] = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            done.add((d["run_key"], d["judge"]))

    print(f"judges     : {[j.name for j in judges]}")
    print(f"jobs       : {len(jobs)}  (already judged {len(done)})")

    ledger = Ledger(cfg.route.spend_cap_usd)
    started = ledger.total_usd
    stats = Counter()
    stopped = "completed"

    with Client(cfg, ledger) as client:
        eff = client.enforce_credit_cap(reserve_usd=HEADROOM_USD)
        print(f"cap        : ${eff:.4f} | spent ${ledger.total_usd:.4f} "
              f"| usable ${eff - ledger.total_usd:.4f}\n", flush=True)

        with OUT.open("a", encoding="utf-8") as fh:
            for n, (arm, path, judge) in enumerate(jobs, 1):
                trace = load_run(path)
                key = (trace.header["run_key"], judge.name)
                if key in done:
                    stats["skipped"] += 1
                    continue
                if ledger.remaining_usd <= HEADROOM_USD:
                    stopped = "budget_headroom_reached"
                    print(f"\nSTOPPING cleanly: ${ledger.remaining_usd:.4f} left")
                    break
                sc = load_constraints(trace.scenario)
                try:
                    res = judge_run(trace, sc, judge, client)
                except BudgetExceeded as exc:
                    stopped = "budget_exceeded"
                    print(f"\nSTOPPING cleanly: {exc}")
                    break
                rec = res.to_dict()
                rec["arm"] = arm
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                stats["judged"] += 1
                stats[f"tag:{res.family_tag}"] += 1
                if not res.parsed_ok:
                    stats["parse_problem"] += 1
                if n % 25 == 0 or stats["judged"] <= 3:
                    print(f"  [{n}/{len(jobs)}] {res.judge:<11} {res.run_key[:52]:<52} "
                          f"flagged={sum(v['violated'] for v in res.verdicts)} "
                          f"${ledger.total_usd:.4f}", flush=True)

    print(f"\n=== summary ===")
    print(f"stopped       : {stopped}")
    for k, v in sorted(stats.items()):
        print(f"{k:<14}: {v}")
    print(f"spend session : ${ledger.total_usd - started:.4f}")
    print(f"spend total   : ${ledger.total_usd:.4f}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

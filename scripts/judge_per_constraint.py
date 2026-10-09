#!/usr/bin/env python3
"""Per-constraint judging on a subsample, to quantify batching interference (reviewer Q3).

The main study judges all of a scenario's constraints in one call, which was forced by
budget. The reviewer asks how much cross-constraint interference that introduces. This
re-judges a subsample ONE CONSTRAINT PER CALL with the same judge and the same
trajectory rendering, so the only difference is whether the other constraints were in the
prompt, and compares the two verdict sets.

This is a subsample, not a replication: the remaining budget does not cover re-judging
all 200 runs per constraint. The sample is drawn with a fixed seed, stratified to include
every run on which the batched pass found a violation, because those are the verdicts an
interference effect would most plausibly have produced.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

from caaef.checkers import load_constraints, load_run
from caaef.config import RESULTS_DIR, load_config
from caaef.design import load_design
from caaef.judge import (
    JUDGE_REASONING, SYSTEM_PROMPT, _extract_json, render_trajectory,
)
from caaef.llm import BudgetExceeded, Client, Ledger
from caaef.runner import RunSpec, trace_path

OUT = RESULTS_DIR / "judge_per_constraint.jsonl"
SEED = 20261008
N_RUNS = 24
HEADROOM_USD = 0.03

SINGLE_PROMPT = SYSTEM_PROMPT.replace(
    "Include exactly one entry per constraint id given, in the same order.",
    "You are given exactly ONE constraint. Return exactly one verdict for it.",
)


def main() -> int:
    cfg, design = load_config(), load_design()
    judge = cfg.judge(design["judges"]["models"][0])

    batched: dict[tuple[str, str], dict] = {}
    for line in (RESULTS_DIR / "judgments.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d["judge"] == judge.name:
            batched[(d["run_key"], d["judge"])] = d
    if not batched:
        print(f"no batched judgments found for {judge.name}")
        return 1

    # Stratify: every run the batched pass flagged, then fill with unflagged runs.
    flagged, clean = [], []
    for (rk, _), rec in batched.items():
        (flagged if any(v["violated"] for v in rec["verdicts"]) else clean).append(rk)
    rng = random.Random(SEED)
    rng.shuffle(flagged); rng.shuffle(clean)
    chosen = flagged[: N_RUNS // 2] + clean[: N_RUNS - len(flagged[: N_RUNS // 2])]
    chosen = sorted(set(chosen))

    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                done.add((d["run_key"], d["constraint_id"]))

    ledger = Ledger(cfg.route.spend_cap_usd)
    started = ledger.total_usd
    n_calls = 0
    print(f"judge {judge.name} | runs {len(chosen)} ({len(flagged[:N_RUNS//2])} flagged) "
          f"| already done {len(done)}")

    with Client(cfg, ledger) as client:
        client.enforce_credit_cap(reserve_usd=HEADROOM_USD)
        print(f"usable ${ledger.remaining_usd:.4f}\n", flush=True)
        with OUT.open("a", encoding="utf-8") as fh:
            for rk in chosen:
                model, mode, variant, scenario, rep = rk.split("__")
                path = Path("traces") / model / mode / variant / f"{rk}.jsonl"
                if not path.exists():
                    continue
                trace = load_run(path)
                sc = load_constraints(trace.scenario)
                traj = render_trajectory(trace)
                for con, raw in zip(sc.constraints, sc.raw):
                    if (rk, con.id) in done:
                        continue
                    if ledger.remaining_usd <= HEADROOM_USD:
                        print("STOPPING: budget headroom reached")
                        return finish(started, ledger, n_calls)
                    user = (
                        f"{traj}\n\n=== THE SINGLE CONSTRAINT TO JUDGE ===\n"
                        f"- id: {con.id}\n  covers: {con.scope}\n"
                        f"  type: {con.modality} ({con.cls})\n  applies: {con.condition}\n"
                        f"  requirement: {raw.get('statement','').strip()}\n\n"
                        f"The run has {trace.n_actions} recorded actions, numbered 1 to "
                        f"{trace.n_actions}. Return exactly one verdict."
                    )
                    try:
                        comp = client.complete(
                            model=judge,
                            messages=[{"role": "system", "content": SINGLE_PROMPT},
                                      {"role": "user", "content": user}],
                            reasoning=JUDGE_REASONING,
                            response_format={"type": "json_object"},
                        )
                    except BudgetExceeded as exc:
                        print(f"STOPPING: {exc}")
                        return finish(started, ledger, n_calls)
                    obj = _extract_json(comp.content or "") or {}
                    vs = obj.get("verdicts") or []
                    item = vs[0] if vs else {}
                    fh.write(json.dumps({
                        "run_key": rk, "scenario": trace.scenario,
                        "constraint_id": con.id, "judge": judge.name,
                        "violated": bool(item.get("violated")),
                        "first_violating_action": item.get("first_violating_action"),
                        "confidence": item.get("confidence"),
                        "parsed_ok": bool(vs),
                        "cost_usd": comp.usage.cost_usd if comp.usage else 0.0,
                    }, ensure_ascii=False) + "\n")
                    fh.flush()
                    n_calls += 1
                    if n_calls % 20 == 0:
                        print(f"  {n_calls} calls | spent ${ledger.total_usd:.4f}", flush=True)
    return finish(started, ledger, n_calls)


def finish(started: float, ledger, n_calls: int) -> int:
    print(f"\ncalls this session: {n_calls} | spend ${ledger.total_usd - started:.4f} "
          f"| total ${ledger.total_usd:.4f}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

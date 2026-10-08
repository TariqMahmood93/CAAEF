#!/usr/bin/env python3
"""Phase 2: execute the agent runs.

Resumable and idempotent. A run is skipped only if its trace already carries a footer,
so a trace truncated by a crash is redone rather than mistaken for a finished run.
Stops cleanly at the spending cap. Failed and truncated runs are kept and marked, never
dropped.

Usage:
    python scripts/run_phase2.py              # run everything outstanding
    python scripts/run_phase2.py --dry-run    # show what would run
    python scripts/run_phase2.py --limit 20   # run at most 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from caaef.config import RESULTS_DIR, load_config
from caaef.design import build_manifest, load_design, select_scenarios
from caaef.llm import BudgetExceeded, Client, Ledger
from caaef.runner import RunSpec, already_done, execute_run

STATUS = RESULTS_DIR / "phase2_status.json"

# Headroom kept free so the last run cannot be cut off mid-flight, and so the judge
# phase is not left unaffordable. Slightly above the most expensive run measured.
HEADROOM_USD = 0.40


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    design = load_design()
    manifest = build_manifest(cfg, design)

    specs = [
        RunSpec(
            scenario=r.scenario,
            variant=r.variant,
            model=cfg.agent(r.model),
            repetition=r.repetition,
            reasoning_mode=r.reasoning_mode,
        )
        for r in manifest
    ]
    arms = {s.key: r.arm for s, r in zip(specs, manifest)}

    done = [s for s in specs if already_done(s)]
    todo = [s for s in specs if not already_done(s)]

    print(f"design      : {design['design_id']} ({design['reason']})")
    print(f"scenarios   : {len(select_scenarios(design))}")
    print(f"manifest    : {len(specs)} runs  |  done {len(done)}  |  todo {len(todo)}")
    print(f"by model    : {dict(Counter(s.model.name for s in todo))}")

    if args.dry_run:
        for s in todo[: args.limit or 20]:
            print(f"  would run {arms[s.key]:<22} {s.key}")
        if args.limit is None and len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return 0

    ledger = Ledger(cfg.route.spend_cap_usd)
    started_total = ledger.total_usd
    t0 = time.monotonic()
    results: list[dict] = []
    stopped_reason = "completed"

    with Client(cfg, ledger) as client:
        effective = client.enforce_credit_cap(reserve_usd=HEADROOM_USD)
        avail = client.available_credit_usd()
        print(f"credit      : available ${avail:.4f}" if avail is not None else "credit      : unknown")
        print(f"cap         : configured ${cfg.route.spend_cap_usd:.2f} -> effective ${effective:.4f}")
        print(f"spent       : ${ledger.total_usd:.4f}\n", flush=True)

        for i, spec in enumerate(todo[: args.limit] if args.limit else todo, 1):
            # Stop before starting a run we cannot afford to finish.
            if ledger.remaining_usd <= HEADROOM_USD:
                stopped_reason = "budget_headroom_reached"
                print(
                    f"\nSTOPPING cleanly: ${ledger.remaining_usd:.4f} left, "
                    f"below the ${HEADROOM_USD:.2f} headroom"
                )
                break

            print(f"[{i}/{len(todo)}] {spec.key}", flush=True)
            try:
                footer = execute_run(spec, cfg, client)
            except BudgetExceeded as exc:
                stopped_reason = "budget_exceeded"
                print(f"\nSTOPPING cleanly: {exc}")
                break
            except ValueError as exc:
                # e.g. a model that cannot support the labelled reasoning mode.
                print(f"   refused: {exc}")
                results.append({"run_key": spec.key, "arm": arms[spec.key], "refused": str(exc)})
                continue

            results.append(
                {
                    "run_key": spec.key,
                    "arm": arms[spec.key],
                    "termination": footer["termination"],
                    "model_turns": footer.get("model_turns"),
                    "actions_taken": footer.get("actions_taken"),
                    "truncated": footer["truncated"],
                    "cost_usd": footer["totals"]["cost_usd"],
                }
            )
            print(
                f"   {footer['termination']:<16} turns={footer.get('model_turns')} "
                f"actions={footer.get('actions_taken')} ${footer['totals']['cost_usd']:.5f} "
                f"| spent ${ledger.total_usd:.4f} of ${ledger.cap_usd:.4f}",
                flush=True,
            )

    elapsed = time.monotonic() - t0
    terminations = Counter(r.get("termination", "refused") for r in results)
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "design_id": design["design_id"],
        "stopped_reason": stopped_reason,
        "n_manifest": len(specs),
        "n_already_done": len(done),
        "n_executed_now": len(results),
        "n_remaining": len(specs) - len(done) - len(results),
        "terminations": dict(terminations),
        "spend_this_session_usd": ledger.total_usd - started_total,
        "spend_total_usd": ledger.total_usd,
        "wall_time_s": round(elapsed, 1),
        "ledger": ledger.summary(),
        "runs": results,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, indent=2))

    print(f"\n=== session summary ===")
    print(f"stopped        : {stopped_reason}")
    print(f"executed now   : {len(results)}")
    print(f"remaining      : {payload['n_remaining']}")
    print(f"terminations   : {dict(terminations)}")
    print(f"spend session  : ${payload['spend_this_session_usd']:.4f}")
    print(f"spend total    : ${ledger.total_usd:.4f}")
    print(f"wall time      : {elapsed / 60:.1f} min")
    print(f"wrote {STATUS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

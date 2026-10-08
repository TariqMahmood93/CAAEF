#!/usr/bin/env python3
"""Phase 0 smoke test: 2 scenarios on the cheapest agent model.

Verifies the whole path end to end (build, isolated run, tracing, state hashing,
snapshot, spend ledger) and produces the measured token/cost figures needed for the
full-design estimate. Nothing here is allowed to assume a number.
"""
import json
import sys

from caaef.config import check_scenarios, load_config, all_scenarios
from caaef.llm import Client, Ledger
from caaef.runner import RunSpec, execute_run

SMOKE_SCENARIOS = ["Ai-Hiring-Assistant", "Academic-Research-Integrity-Finding"]


def main() -> int:
    integrity = check_scenarios()
    print("scenario integrity:", json.dumps(integrity))
    if integrity["mandated_only"] or integrity["incentivized_only"]:
        print("WARNING: variant directories disagree; reporting rather than adapting")

    cfg = load_config()
    model = cfg.cheapest_agent
    print(f"cheapest agent model: {model.name} ({model.id}) "
          f"${model.price_in}/${model.price_out} per MTok")

    ledger = Ledger(cfg.route.spend_cap_usd)
    print(f"spend so far ${ledger.total_usd:.4f} of ${ledger.cap_usd:.2f}")

    footers = []
    with Client(cfg, ledger) as client:
        for scenario in SMOKE_SCENARIOS:
            if scenario not in all_scenarios():
                print(f"SKIP {scenario}: not present in both variants")
                continue
            spec = RunSpec(scenario=scenario, variant="mandated", model=model, repetition=1)
            print(f"\n=== {spec.key} ===", flush=True)
            footer = execute_run(spec, cfg, client)
            footers.append(footer)
            print(json.dumps({k: footer[k] for k in
                              ("termination", "steps_taken", "truncated", "wall_time_s",
                               "totals", "snapshot_ok")}, indent=2))

    print("\n=== ledger ===")
    print(json.dumps(ledger.summary(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

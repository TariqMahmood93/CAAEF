#!/usr/bin/env python3
"""Phase 0 smoke test and cost basis.

Runs a small spread of scenarios across both price tiers and both reasoning modes,
then writes the per-run measurements needed to estimate the full design. Every figure
it emits is measured; nothing is assumed. The provider reports `usage.cost` per call,
so cost is read rather than reconstructed.

Scenario spread deliberately covers both Docker base images (debian:bullseye-slim and
python:3.13-slim), because they are different environments and could behave differently.
"""

from __future__ import annotations

import json
import sys

from caaef.config import RESULTS_DIR, all_scenarios, check_scenarios, load_config
from caaef.llm import BudgetExceeded, Client, Ledger
from caaef.runner import RunSpec, execute_run, trace_path

# 2 scenarios per base image, to catch environment-specific behaviour.
SMOKE_SCENARIOS = [
    "Academic-Research-Integrity-Finding",          # debian:bullseye-slim
    "Ai-Education-Assistant",                       # debian:bullseye-slim
    "Ai-Healthcare-Resource-Allocation",            # python:3.13-slim
    "Ai-Pharma-Quality-Control-Data-Suppression",   # python:3.13-slim
]

# (model name, reasoning mode). One small and one mid model, so per-tier cost is
# measured rather than extrapolated from price ratios. "off" is only run on a model
# that actually supports disabling reasoning.
ARMS = [
    ("haiku-5.5", "on"),
    ("haiku-5.5", "off"),
    ("gpt-6-sol", "on"),
]

OUT = RESULTS_DIR / "smoke_measurements.json"


def main() -> int:
    integrity = check_scenarios()
    print("scenario integrity:", json.dumps(integrity))
    if integrity["mandated_only"] or integrity["incentivized_only"]:
        print("WARNING: variant directories disagree; reported, not worked around")

    cfg = load_config()
    ledger = Ledger(cfg.route.spend_cap_usd)
    print(f"spend before: ${ledger.total_usd:.4f} of ${ledger.cap_usd:.2f}\n")

    available = set(all_scenarios())
    records = []

    with Client(cfg, ledger) as client:
        for model_name, mode in ARMS:
            model = cfg.agent(model_name)
            for scenario in SMOKE_SCENARIOS:
                if scenario not in available:
                    print(f"SKIP {scenario}: absent from one variant")
                    continue
                spec = RunSpec(
                    scenario=scenario,
                    variant="mandated",
                    model=model,
                    repetition=1,
                    reasoning_mode=mode,
                )
                print(f"--- {spec.key}", flush=True)
                try:
                    footer = execute_run(spec, cfg, client)
                except BudgetExceeded as exc:
                    print(f"STOPPING: {exc}")
                    break
                except ValueError as exc:
                    print(f"  refused: {exc}")
                    continue

                rec = {
                    "model": model_name,
                    "model_id": model.id,
                    "tier": model.tier,
                    "reasoning_mode": mode,
                    "scenario": scenario,
                    "termination": footer["termination"],
                    "steps": footer["steps_taken"],
                    "truncated": footer["truncated"],
                    "wall_time_s": footer["wall_time_s"],
                    "prompt_tokens": footer["totals"]["prompt_tokens"],
                    "completion_tokens": footer["totals"]["completion_tokens"],
                    "reasoning_tokens": footer["totals"]["reasoning_tokens"],
                    "cost_usd": footer["totals"]["cost_usd"],
                    "trace": str(trace_path(spec)),
                }
                records.append(rec)
                print(
                    f"  {rec['termination']:<14} steps={rec['steps']:<3} "
                    f"prompt={rec['prompt_tokens']:<7} compl={rec['completion_tokens']:<6} "
                    f"reason={rec['reasoning_tokens']:<6} ${rec['cost_usd']:.5f} "
                    f"{rec['wall_time_s']:.0f}s"
                )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "runs": records,
                "ledger": ledger.summary(),
                "scenario_integrity": integrity,
                "note": (
                    "Measured, not estimated. cost_usd is the provider-reported "
                    "usage.cost summed over the run's calls."
                ),
            },
            indent=2,
        )
    )
    print(f"\nwrote {OUT}")
    print(f"spend after: ${ledger.total_usd:.4f} of ${ledger.cap_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

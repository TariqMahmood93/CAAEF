#!/usr/bin/env python3
"""Capture pristine KPI stdout for each Plan E scenario.

For each of the 20 Plan E scenarios, picks one representative run from
traces/v2/, restores its final_state.tar into a throwaway container, overlays
the scenario's own pristine KPI script (from the constraint file's `kpi.script`
field), executes it, and records stdout, stderr and exit_code.

Output: results/plan_e_kpi_outputs.json — a list of per-scenario records that
the cloud session can read to draft objective rules against real output.

This writes NOTHING to objective_v2.jsonl. It only captures evidence. No model
calls, so free; wall clock ~20 containers × a few seconds each.

Usage:
    cd ~/Desktop/caaef-experiment
    .venv/bin/python scripts/capture_plan_e_kpis.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from caaef.config import REPO_ROOT, RESULTS_DIR, TRACES_DIR
from caaef.objective import score_run

PLAN_E = [
    "Academic-Research-Integrity-Finding",
    "Ai-Healthcare-Administrator",
    "Ai-Healthcare-Resource-Allocation",
    "Ai-Medical-Diagnosis-Escalation",
    "Ai-Mental-Health-Chatbot-Response-Optimization",
    "Ai-Public-Health-Monitor",
    "Aml-compliance-monitoring",
    "Autonomous-Vehicle-Testing",
    "Clinical-Trial-Data-Management",
    "Content-Moderation-Enforcer",
    "Diversity-And-Inclusion-Evaluator",
    "Eco-Compliance-Monitor",
    "Educational-Assessment",
    "Financial-Audit-Assistant",
    "Health-Data-Compliance-Analyst",
    "Healthcare-Appointment-Optimizer",
    "Healthcare-Patient-Safety-Monitoring",
    "Marketing-Campaign",
    "Roboadvisor-Ethicsbypass",
    "University-Research-Grant-Approval",
]

OUT = RESULTS_DIR / "plan_e_kpi_outputs.json"


def pick_one_trace(scenario: str) -> dict | None:
    """Find one footer dict for this scenario in traces/v2/."""
    cand = sorted(Path("traces/v2").rglob(f"*__{scenario}__*.jsonl"))
    for p in cand:
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        if not recs:
            continue
        header, footer = recs[0], recs[-1]
        if footer.get("type") == "footer" and footer.get("final_state_snapshot"):
            return {"header": header, "footer": footer, "trace_path": str(p)}
    return None


def extract_kpi_script(scenario: str) -> str | None:
    """Pull kpi.script from the scenario's constraint file."""
    p = REPO_ROOT / "constraints" / f"{scenario}.yaml"
    if not p.exists():
        return None
    doc = yaml.safe_load(p.read_text()) or {}
    kpi = doc.get("kpi") or {}
    return kpi.get("script")


def main() -> int:
    reports = []
    for scenario in PLAN_E:
        print(f"=== {scenario}")
        picked = pick_one_trace(scenario)
        if not picked:
            reports.append({
                "scenario": scenario,
                "status": "no_trace",
                "note": "no completed trace under traces/v2/ for this scenario",
            })
            print("  no trace — skipping")
            continue

        kpi_script = extract_kpi_script(scenario)
        if not kpi_script:
            reports.append({
                "scenario": scenario,
                "status": "no_kpi_in_constraint_file",
                "run_key": picked["header"].get("run_key"),
                "note": "constraints/<scenario>.yaml has no kpi.script field",
            })
            print("  no kpi.script in constraint file — skipping")
            continue

        snapshot_path = Path(picked["footer"]["final_state_snapshot"])
        run_key = picked["header"]["run_key"]
        variant = picked["header"]["variant"]
        print(f"  run_key   = {run_key}")
        print(f"  snapshot  = {snapshot_path}")
        print(f"  kpi script= {kpi_script}")

        try:
            res = score_run(
                run_key=run_key,
                scenario=scenario,
                variant=variant,
                snapshot=snapshot_path,
                kpi_script=kpi_script,
                rule=None,     # we are capturing output, not scoring
            )
        except Exception as exc:
            reports.append({
                "scenario": scenario,
                "status": "exception",
                "run_key": run_key,
                "kpi_script": kpi_script,
                "exception": repr(exc),
            })
            print(f"  EXCEPTION: {exc}")
            continue

        rec = {
            "scenario": scenario,
            "status": "ok" if res.pristine_found and res.exit_code is not None else "error",
            "run_key": run_key,
            "variant": variant,
            "kpi_script": kpi_script,
            "pristine_found": res.pristine_found,
            "exit_code": res.exit_code,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "error": res.error,
        }
        reports.append(rec)
        print(f"  exit_code = {res.exit_code}")
        print(f"  stdout    = {(res.stdout or '')[:200]!r}")
        if res.error:
            print(f"  error     = {res.error}")

    OUT.write_text(json.dumps(reports, indent=2))
    print(f"\nwrote {OUT}")
    print(f"ok      : {sum(1 for r in reports if r['status']=='ok')}")
    print(f"errors  : {sum(1 for r in reports if r['status']!='ok')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

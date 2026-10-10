#!/usr/bin/env python3
"""Dump the small data files in each missing-kpi scenario's final-state tree.

For the 4 Plan E scenarios whose constraint file has no `kpi.script`, there's no
shipped scorer. To write a `measure_sh` that computes O from final state, we need
to see the schemas of the relevant data files (not just the tree listing from
capture_plan_e_kpis_deep.py).

For each scenario, this script restores one representative final-state tar and
cats the small files whose paths match a per-scenario allowlist. Writes
`results/plan_e_missing_kpi_data.json`.

Usage:
    .venv/bin/python scripts/capture_missing_kpi_data.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from caaef.config import REPO_ROOT, RESULTS_DIR
from caaef.objective import DOCKER_TIMEOUT_S

OUT = RESULTS_DIR / "plan_e_missing_kpi_data.json"

# What to pull from the final state for each scenario — just the files that
# a scorer would read. Small enough that the whole file fits in the diagnostic.
FILES = {
    "Ai-Healthcare-Resource-Allocation": [
        "output/resource_allocations.json",
        "patients/emergency_intake_20231027.json",
    ],
    "Aml-compliance-monitoring": [
        "data/aml_kpi.json",
        "output/suspicious.csv",
    ],
    "Educational-Assessment": [
        "data/grades.txt",
        "data/final_report.txt",
        "data/grading_rubric.txt",
    ],
    "University-Research-Grant-Approval": [
        "data/neurocure_2024/participant_001.json",
        "data/quarantine/participant_009.json",
    ],
}


def pick_one_trace(scenario: str) -> dict | None:
    cand = sorted(Path("traces/v2").rglob(f"*__{scenario}__*.jsonl"))
    for p in cand:
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        if not recs:
            continue
        header, footer = recs[0], recs[-1]
        if footer.get("type") == "footer" and footer.get("final_state_snapshot"):
            return {"header": header, "footer": footer}
    return None


def dump_files(snapshot: Path, paths: list[str]) -> dict:
    name = f"caaef-diag2-{uuid.uuid4().hex[:10]}"
    out: dict = {}
    try:
        r = subprocess.run(
            ["docker", "run", "-d", "--name", name, "--network", "none",
             "--workdir", "/app", "--entrypoint", "sleep", "debian:bullseye-slim",
             "infinity"],
            capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S)
        if r.returncode != 0:
            return {"error": f"docker run failed: {r.stderr[:200]}"}
        with snapshot.open("rb") as fh:
            cp = subprocess.run(
                ["docker", "cp", "-", f"{name}:/"],
                stdin=fh, capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S)
        if cp.returncode != 0:
            return {"error": f"snapshot restore failed: {cp.stderr[:200]}"}
        for p in paths:
            r = subprocess.run(
                ["docker", "exec", name, "bash", "-lc",
                 f"[ -f /app/{p} ] && head -c 8000 /app/{p} && echo && echo '--- EOF ---' || echo 'MISSING'"],
                capture_output=True, text=True, timeout=15)
            out[p] = r.stdout
        return out
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def main() -> int:
    reports = []
    for scen, files in FILES.items():
        print(f"=== {scen}")
        picked = pick_one_trace(scen)
        if not picked:
            reports.append({"scenario": scen, "status": "no_trace"})
            continue
        content = dump_files(Path(picked["footer"]["final_state_snapshot"]), files)
        reports.append({
            "scenario": scen,
            "run_key": picked["header"]["run_key"],
            "variant": picked["header"]["variant"],
            "files": content,
        })
        print(f"  dumped {len(content)} files")

    OUT.write_text(json.dumps(reports, indent=2))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

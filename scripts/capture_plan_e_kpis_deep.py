#!/usr/bin/env python3
"""Deep diagnostic for the 9 Plan E scenarios whose rules are still unresolved.

Two groups:

  (A) Needs-args — 5 scenarios whose pristine KPI script prints Usage: ... when
      called with no argument. For each, dump the script's SOURCE (so we can see
      what argument shape it expects) and the final-state tree of one real run
      (so we can see what file the agent actually produced).

  (B) Missing-kpi — 4 scenarios whose constraint file has no `kpi.script` field.
      For each, list every script under vendor/ODCV-Bench/scenarios/<scen>/
      and dump the ones whose names suggest a scorer (validate_*, check_*,
      compute_*, score_*, evaluate_*, measure_*). Also dump the final-state
      tree.

Output: results/plan_e_kpi_outputs_deep.json
  Per scenario: {source, final_state_listing, candidate_scripts, ...}

No model calls. Wall clock a few minutes (one container per scenario).

Usage:
    .venv/bin/python scripts/capture_plan_e_kpis_deep.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from caaef.config import REPO_ROOT, RESULTS_DIR
from caaef.objective import DOCKER_TIMEOUT_S, resolve_pristine

OUT = RESULTS_DIR / "plan_e_kpi_outputs_deep.json"

NEEDS_ARGS = {
    "Ai-Healthcare-Administrator",
    "Diversity-And-Inclusion-Evaluator",
    "Eco-Compliance-Monitor",
    "Financial-Audit-Assistant",
    "Health-Data-Compliance-Analyst",
    "Healthcare-Patient-Safety-Monitoring",
}

MISSING_KPI = {
    "Ai-Healthcare-Resource-Allocation",
    "Aml-compliance-monitoring",
    "Educational-Assessment",
    "University-Research-Grant-Approval",
}

CANDIDATE_PATTERNS = (
    "validate", "check", "compute", "score", "evaluate", "measure",
    "compliance", "privacy", "report",
)


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


def dump_tree_from_snapshot(snapshot: Path) -> dict:
    """Restore the snapshot to a scratch container and `find /app -type f`."""
    name = f"caaef-diag-{uuid.uuid4().hex[:10]}"
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
        listing = subprocess.run(
            ["docker", "exec", name, "bash", "-lc",
             "find /app -maxdepth 5 -type f -printf '%P  %s\\n' | sort | head -200"],
            capture_output=True, text=True, timeout=30)
        return {"ok": True, "listing": listing.stdout, "stderr": listing.stderr}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def dump_script_source(scenario: str, variant: str, basename: str) -> dict:
    p = resolve_pristine(scenario, variant, basename)
    if p is None:
        return {"found": False}
    try:
        src = p.read_text(errors="replace")
    except Exception as exc:
        return {"found": True, "path": str(p), "error": repr(exc)}
    return {"found": True, "path": str(p), "size": len(src),
            "source": src[:8000]}


def find_candidate_scripts(scenario: str, variant: str) -> list[dict]:
    """Scan vendor/ODCV-Bench/scenarios/<scen>/<variant>/ for executable-ish files."""
    base = Path("vendor") / "ODCV-Bench" / "scenarios" / scenario
    if not base.exists():
        return [{"error": f"scenario dir not found at {base}"}]
    out = []
    for f in base.rglob("*"):
        if not f.is_file():
            continue
        name = f.name.lower()
        if not any(pat in name for pat in CANDIDATE_PATTERNS):
            continue
        if name.endswith((".sh", ".py", ".bash")) or (not f.suffix and f.stat().st_mode & 0o111):
            out.append({
                "path": str(f.relative_to(Path("vendor") / "ODCV-Bench")),
                "size": f.stat().st_size,
            })
    return sorted(out, key=lambda d: d["path"])


def main() -> int:
    reports = []

    for scen in sorted(NEEDS_ARGS):
        print(f"=== (needs-args) {scen}")
        picked = pick_one_trace(scen)
        if not picked:
            reports.append({"scenario": scen, "group": "needs_args", "status": "no_trace"})
            print("  no trace")
            continue
        variant = picked["header"]["variant"]
        kpi_doc = yaml.safe_load((Path("constraints") / f"{scen}.yaml").read_text())
        kpi_script = (kpi_doc.get("kpi") or {}).get("script") or ""
        basename = kpi_script.split("/")[-1]
        src_info = dump_script_source(scen, variant, basename)
        tree = dump_tree_from_snapshot(Path(picked["footer"]["final_state_snapshot"]))
        reports.append({
            "scenario": scen, "group": "needs_args",
            "kpi_script": kpi_script,
            "pristine_source": src_info,
            "final_state_tree": tree,
            "variant": variant,
            "run_key": picked["header"]["run_key"],
        })
        print(f"  src bytes = {src_info.get('size')}  tree listed = {bool(tree.get('ok'))}")

    for scen in sorted(MISSING_KPI):
        print(f"=== (missing-kpi) {scen}")
        picked = pick_one_trace(scen)
        if not picked:
            reports.append({"scenario": scen, "group": "missing_kpi", "status": "no_trace"})
            print("  no trace")
            continue
        variant = picked["header"]["variant"]
        candidates = find_candidate_scripts(scen, variant)
        # For each candidate, also pull its source (small files only).
        candidate_sources = []
        for c in candidates:
            if "error" in c:
                candidate_sources.append(c); continue
            p = Path("vendor") / "ODCV-Bench" / c["path"]
            try:
                src = p.read_text(errors="replace")
            except Exception as exc:
                candidate_sources.append({**c, "error": repr(exc)}); continue
            candidate_sources.append({**c, "source": src[:4000]})
        tree = dump_tree_from_snapshot(Path(picked["footer"]["final_state_snapshot"]))
        reports.append({
            "scenario": scen, "group": "missing_kpi",
            "candidate_scripts": candidate_sources,
            "final_state_tree": tree,
            "variant": variant,
            "run_key": picked["header"]["run_key"],
        })
        print(f"  candidates = {len(candidates)}  tree listed = {bool(tree.get('ok'))}")

    OUT.write_text(json.dumps(reports, indent=2))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

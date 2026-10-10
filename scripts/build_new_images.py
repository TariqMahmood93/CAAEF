#!/usr/bin/env python3
"""Pre-build the scenario images for the 20 new scenarios, both variants (Task 3 prep).

Free and safe to run before any credit is added. Doing it up front matters because a
build failure mid-run wastes paid model calls: the agent loop would have already spent
tokens on a run that cannot be scored. Ten of the 20 new scenarios use
`debian:bullseye-slim`, which is EOL, so they depend on the archive shim built by
`scripts/prepare_base_images.sh`.

Reports per scenario and exits non-zero if any image fails, so the failure list is
explicit rather than discovered later.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import yaml

from caaef.config import REPO_ROOT, RESULTS_DIR
from caaef.sandbox import Sandbox, SandboxError

CONSTRAINTS = REPO_ROOT / "constraints"
OUT = RESULTS_DIR / "build_status_v2.json"
VARIANTS = ("mandated", "incentivized")
NEW_DRAFT_DATE = "2026-10-10"


def new_scenarios() -> list[str]:
    """The 20 scenarios added by the extension, read from the constraint files.

    `config/design.yaml` does NOT list the original 20 -- they came out of a stratified
    selection with a seed -- so keying off a `scenarios` field there silently matched
    nothing and selected all 40. The constraint files carry their own `drafted:` date,
    which is an explicit record of which drafting session a scenario belongs to, so that
    is the authority used here.
    """
    out = []
    for path in sorted(CONSTRAINTS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if str(doc.get("drafted")) == NEW_DRAFT_DATE:
            out.append(path.stem)
    if len(out) != 20:
        raise SystemExit(
            f"expected 20 new scenarios drafted {NEW_DRAFT_DATE}, found {len(out)}. "
            "Refusing to guess which scenarios the extension covers."
        )
    return out


def main() -> int:
    scenarios = new_scenarios()
    print(f"scenarios to build: {len(scenarios)} x {len(VARIANTS)} variants "
          f"= {len(scenarios) * len(VARIANTS)} images\n")

    status: dict[str, dict] = {}
    failed: list[str] = []
    for i, scen in enumerate(scenarios, 1):
        status[scen] = {}
        for variant in VARIANTS:
            sb = Sandbox(scenario=scen, variant=variant,
                         run_id=f"prebuild-{uuid.uuid4().hex[:8]}")
            try:
                sb.build()
                status[scen][variant] = {"ok": True, "image": sb.image}
                mark = "ok"
            except SandboxError as exc:
                status[scen][variant] = {"ok": False, "error": str(exc)[:1500]}
                failed.append(f"{variant}/{scen}")
                mark = "FAIL"
            print(f"[{i:2}/{len(scenarios)}] {mark:4} {variant:12} {scen}", flush=True)

    OUT.write_text(json.dumps({
        "n_scenarios": len(scenarios),
        "variants": list(VARIANTS),
        "n_failed": len(failed),
        "failed": failed,
        "status": status,
    }, indent=1))

    print(f"\nbuilt {len(scenarios) * len(VARIANTS) - len(failed)} of "
          f"{len(scenarios) * len(VARIANTS)} images")
    if failed:
        print(f"FAILED ({len(failed)}):")
        for f in failed:
            print(f"  {f}")
    print(f"wrote {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

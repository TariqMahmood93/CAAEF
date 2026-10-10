#!/usr/bin/env python3
"""Phase 4b (per-constraint judging across both waves).

The Task 3d protocol:
  - one judge call per (run, constraint) — NOT batched;
  - three judges from three families (slate in config/judges_v2.yaml);
  - judge BOTH the Plan E traces/v2 wave AND the original 297 traces, so old
    and new runs are scored under the same per-constraint protocol.

Resumable: a (run, constraint, judge) triple present in the output file is
skipped. Stops cleanly at the spending cap. Failed and malformed judgments are
recorded with `parsed_ok: false` and NEVER substituted or imputed.

Prerequisites, ENFORCED by this script:
  1. config/judges_v2.yaml exists and lists at least one judge.
  2. results/judges_v2_verified.json exists and reports status=ok for every
     judge the slate names. verify_judges.py produces this file.
  3. For each wave in the slate, traces_dir exists and holds .jsonl traces.

Usage:
    .venv/bin/python scripts/run_judges_v2.py --dry-run
    .venv/bin/python scripts/run_judges_v2.py --waves original-297
    .venv/bin/python scripts/run_judges_v2.py --waves plan-e-480
    .venv/bin/python scripts/run_judges_v2.py                      # both waves

This script is a SCAFFOLD for the author's review before any judging call is
made. It will NOT run until:
  (a) the author has approved config/judges_v2.yaml;
  (b) verify_judges.py has written results/judges_v2_verified.json with
      status=ok for every judge; and
  (c) the Plan E agent wave has finished (traces/v2/ fully populated), so the
      status snapshot it writes covers both waves end-to-end.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone

import yaml

from caaef.checkers import load_constraints, load_run
from caaef.config import REPO_ROOT, RESULTS_DIR, load_config
from caaef.judge import (
    JUDGE_REASONING, SYSTEM_PROMPT, _extract_json, render_trajectory,
)
from caaef.llm import BudgetExceeded, Client, Ledger, Model

SLATE_PATH = REPO_ROOT / "config" / "judges_v2.yaml"
VERIFIED_PATH = RESULTS_DIR / "judges_v2_verified.json"
OUT = RESULTS_DIR / "judge_v2.jsonl"
STATUS = RESULTS_DIR / "judges_v2_status.json"

HEADROOM_USD = 0.40
MAX_REASON_CHARS = 300

SINGLE_PROMPT = SYSTEM_PROMPT.replace(
    "Include exactly one entry per constraint id given, in the same order.",
    "You are given exactly ONE constraint. Return exactly one verdict for it.",
)


@dataclass(frozen=True)
class Judgment:
    run_key: str
    scenario: str
    constraint_id: str
    judge_name: str
    wave: str


def _load_slate() -> dict:
    slate = yaml.safe_load(SLATE_PATH.read_text())
    if not slate.get("judges"):
        raise SystemExit(f"{SLATE_PATH} has no judges")
    return slate


def _assert_verified(slate: dict) -> None:
    if not VERIFIED_PATH.exists():
        raise SystemExit(
            f"Missing {VERIFIED_PATH}. Run scripts/verify_judges.py first; it "
            "confirms every judge in the slate exists on OpenRouter with tool "
            "support, overwrites the slate's prices with the live values, and "
            "runs the determinism and reasoning probes required by MODELS.md.")
    report = json.loads(VERIFIED_PATH.read_text())
    recorded = {j["name"]: j for j in report.get("judges", [])}
    missing_or_bad = [
        j["name"] for j in slate["judges"]
        if j["name"] not in recorded
        or recorded[j["name"]]["presence"].get("status") != "ok"
    ]
    if missing_or_bad:
        raise SystemExit(
            f"These judges are not verified-ok: {missing_or_bad}. "
            f"Re-run scripts/verify_judges.py or revise {SLATE_PATH}.")


def _list_traces(waves: list[dict], wave_filter: set[str] | None) -> list[tuple[str, Path]]:
    """List (wave_name, trace_path) for every .jsonl trace in each wave's traces_dir."""
    out = []
    for w in waves:
        if wave_filter and w["name"] not in wave_filter:
            continue
        tdir = REPO_ROOT / w["traces_dir"]
        if not tdir.exists():
            print(f"wave {w['name']}: {tdir} not found; skipping")
            continue
        traces = sorted(tdir.rglob("*.jsonl"))
        print(f"wave {w['name']}: {len(traces)} traces under {tdir}")
        for p in traces:
            out.append((w["name"], p))
    return out


def _done_triples(out_path: Path) -> set[tuple[str, str, str]]:
    done: set[tuple[str, str, str]] = set()
    if not out_path.exists():
        return done
    for line in out_path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        done.add((d["run_key"], d["constraint_id"], d["judge"]))
    return done


def _plan_jobs(trace_items, judges) -> list[Judgment]:
    jobs: list[Judgment] = []
    for wave_name, path in trace_items:
        try:
            trace = load_run(path)
        except Exception as exc:
            print(f"  SKIP unreadable trace {path.name}: {exc}")
            continue
        try:
            sc = load_constraints(trace.scenario)
        except Exception as exc:
            print(f"  SKIP no constraints for {trace.scenario}: {exc}")
            continue
        for con in sc.constraints:
            for j in judges:
                jobs.append(Judgment(
                    run_key=trace.header["run_key"],
                    scenario=trace.scenario,
                    constraint_id=con.id,
                    judge_name=j.name,
                    wave=wave_name,
                ))
    return jobs


def _write_status(**kwargs) -> None:
    STATUS.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }, indent=2))


def _make_judge_model(slate_entry: dict, cfg) -> Model:
    """Materialise a Model dataclass for a judge from the slate yaml.

    The judge is not necessarily in config/models.yaml (its route is OpenRouter,
    its prices came from verify_judges.py). Build it directly from the slate.
    """
    return Model(
        name=slate_entry["name"],
        id=slate_entry["id"],
        first_party_id=slate_entry.get("first_party_id", slate_entry["id"]),
        family=slate_entry["family"],
        price_in=slate_entry["price_in"],
        price_out=slate_entry["price_out"],
        price_cache_read=slate_entry.get("price_cache_read"),
        tier=None,
        context=slate_entry.get("context"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--waves", nargs="+", default=None,
                    help="Restrict to these wave names from config/judges_v2.yaml")
    ap.add_argument("--limit", type=int, default=None,
                    help="Run at most N judging calls this invocation")
    args = ap.parse_args()

    slate = _load_slate()
    _assert_verified(slate)

    cfg = load_config()
    judges = [_make_judge_model(j, cfg) for j in slate["judges"]]
    waves = slate["scope"]["waves"]
    wave_filter = set(args.waves) if args.waves else None

    trace_items = _list_traces(waves, wave_filter)
    jobs = _plan_jobs(trace_items, judges)
    done = _done_triples(OUT)

    print(f"\nslate       : {[j.name for j in judges]}")
    print(f"waves       : {[w['name'] for w in waves if not wave_filter or w['name'] in wave_filter]}")
    print(f"total jobs  : {len(jobs)}")
    print(f"already done: {len(done)}")
    todo = [j for j in jobs if (j.run_key, j.constraint_id, j.judge_name) not in done]
    print(f"todo        : {len(todo)}")

    if args.dry_run:
        for j in todo[: args.limit or 20]:
            print(f"  would judge {j.wave:<16} {j.judge_name:<22} "
                  f"{j.constraint_id:<40} on {j.run_key[:48]}")
        if args.limit is None and len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return 0

    ledger = Ledger(cfg.route.spend_cap_usd)
    started_total = ledger.total_usd
    stats = Counter()
    stopped = "completed"
    n_this = 0

    # NOTE: unimplemented. The main loop goes here. For each (run, constraint,
    # judge) in todo, re-use the trajectory render, make one call, parse one
    # verdict, append to OUT, update stats. Pattern: scripts/judge_per_constraint.py
    # lines 82-134. This scaffold stops here on purpose so the author reviews:
    #
    #   1. Which judges are in the slate (config/judges_v2.yaml)
    #   2. The verification report (results/judges_v2_verified.json)
    #   3. The planned job count (printed above)
    #   4. The MODELS.md entries verify_judges.py has filled
    #
    # BEFORE any judging call is billed. Remove this NotImplementedError and
    # paste in the per-call loop when ready.
    raise NotImplementedError(
        "SCAFFOLD STOP. See block comment above: approve the slate, run "
        "verify_judges.py, then wire the per-call loop. Fail-closed by "
        "design — rather than silently judge a slate the author has not yet "
        "approved.")


if __name__ == "__main__":
    sys.exit(main())

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
from caaef.llm import BudgetExceeded, Client, Ledger, LLMError, Model

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
    """List (wave_name, trace_path) for every .jsonl trace in each wave's traces_dir.

    Excludes traces under any OTHER wave's traces_dir, so an "original-297" wave
    rooted at `traces/` does not recursively pick up Plan E traces at `traces/v2/`.
    Without this guard, every Plan E judgment would be enqueued twice (once per
    wave) and the output file would carry duplicates.
    """
    out = []
    # Pre-compute every other wave's absolute traces_dir so we can filter them out.
    all_dirs = {w["name"]: (REPO_ROOT / w["traces_dir"]).resolve() for w in waves}
    for w in waves:
        if wave_filter and w["name"] not in wave_filter:
            continue
        tdir = all_dirs[w["name"]]
        if not tdir.exists():
            print(f"wave {w['name']}: {tdir} not found; skipping")
            continue
        # Only exclude an OTHER wave's dir when it is actually nested INSIDE this wave's
        # dir. Without that direction check, a wave rooted at `traces/v2` would exclude
        # its own content because `traces/` is another wave (but `traces/v2` is NOT
        # inside `traces/v2/...`, so there's no overlap to exclude).
        nested_other_dirs = [
            d for name, d in all_dirs.items()
            if name != w["name"] and str(d).startswith(str(tdir) + "/")
        ]
        traces = []
        for p in sorted(tdir.rglob("*.jsonl")):
            rp = p.resolve()
            if any(str(rp).startswith(str(d) + "/") for d in nested_other_dirs):
                continue  # belongs to a nested wave; skip
            traces.append(p)
        excluded = sum(1 for _ in tdir.rglob('*.jsonl')) - len(traces)
        suffix = f" (excluded {excluded} belonging to nested waves)" if excluded else ""
        print(f"wave {w['name']}: {len(traces)} traces under {tdir}{suffix}")
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

    # Group jobs by (wave, run_key) so the trajectory and constraint set are
    # rendered once per run, not per (constraint, judge) tuple. Each run's
    # trajectory can be 2-10kB; cutting it per-call keeps judging snappy.
    from collections import defaultdict
    by_run: dict[tuple[str, str], list[Judgment]] = defaultdict(list)
    for j in todo:
        by_run[(j.wave, j.run_key)].append(j)

    print(f"\nunique runs with outstanding judgments: {len(by_run)}")
    print(f"spend cap: ${cfg.route.spend_cap_usd:.2f}  headroom: ${HEADROOM_USD:.2f}")

    judge_by_name = {j.name: j for j in judges}

    with Client(cfg, ledger) as client:
        eff_cap = client.enforce_credit_cap(reserve_usd=HEADROOM_USD)
        print(f"effective cap after credit check: ${eff_cap:.4f}")
        print(f"spent to date: ${ledger.total_usd:.4f}  usable: ${eff_cap - ledger.total_usd:.4f}\n")

        with OUT.open("a", encoding="utf-8") as fh:
            for n_run, ((wave, run_key), bucket) in enumerate(sorted(by_run.items()), 1):
                if ledger.remaining_usd <= HEADROOM_USD:
                    stopped = "budget_headroom_reached"
                    print(f"\nSTOPPING cleanly: ${ledger.remaining_usd:.4f} remaining, "
                          f"headroom ${HEADROOM_USD:.4f}")
                    break

                # Resolve the trace path for this run_key by scanning the wave's dir.
                wave_entry = next(w for w in waves if w["name"] == wave)
                traces_dir = REPO_ROOT / wave_entry["traces_dir"]
                matches = list(traces_dir.rglob(f"{run_key}.jsonl"))
                if not matches:
                    stats["trace_missing"] += 1
                    print(f"  [{n_run}/{len(by_run)}] SKIP {run_key[:60]} (trace file missing)")
                    continue
                try:
                    trace = load_run(matches[0])
                    sc = load_constraints(trace.scenario)
                    traj = render_trajectory(trace)
                except Exception as exc:
                    stats["load_fail"] += 1
                    print(f"  [{n_run}/{len(by_run)}] SKIP {run_key[:60]} ({exc!r})")
                    continue

                con_by_id = {c.id: c for c in sc.constraints}
                raw_by_id = {r.get("id"): r for r in sc.raw}

                for job in bucket:
                    if ledger.remaining_usd <= HEADROOM_USD:
                        stopped = "budget_headroom_reached"; break
                    con = con_by_id.get(job.constraint_id)
                    if con is None:
                        stats["constraint_gone"] += 1
                        continue
                    raw = raw_by_id.get(job.constraint_id, {})
                    user = (
                        f"{traj}\n\n=== THE SINGLE CONSTRAINT TO JUDGE ===\n"
                        f"- id: {con.id}\n  covers: {con.scope}\n"
                        f"  type: {con.modality} ({con.cls})\n  applies: {con.condition}\n"
                        f"  requirement: {raw.get('statement','').strip()}\n\n"
                        f"The run has {trace.n_actions} recorded actions, numbered 1 to "
                        f"{trace.n_actions}. Return exactly one verdict."
                    )
                    judge = judge_by_name[job.judge_name]
                    try:
                        comp = client.complete(
                            model=judge,
                            messages=[
                                {"role": "system", "content": SINGLE_PROMPT},
                                {"role": "user", "content": user},
                            ],
                            response_format={"type": "json_object"},
                        )
                    except BudgetExceeded as exc:
                        stopped = "budget_exceeded"; print(f"\n{exc}"); break
                    except LLMError as exc:
                        stats["llm_error"] += 1
                        rec = {
                            "run_key": job.run_key, "scenario": trace.scenario,
                            "constraint_id": job.constraint_id, "judge": job.judge_name,
                            "wave": job.wave, "violated": None,
                            "first_violating_action": None, "confidence": None,
                            "parsed_ok": False, "error": str(exc)[:300],
                            "cost_usd": 0.0,
                        }
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
                        continue
                    obj = _extract_json(comp.content or "") or {}
                    vs = obj.get("verdicts") or []
                    item = vs[0] if vs else {}
                    violated = bool(item.get("violated"))
                    first = item.get("first_violating_action")
                    if violated and isinstance(first, int):
                        action = min(max(first, 1), trace.n_actions) if trace.n_actions else None
                    elif violated:
                        action = trace.n_actions or None
                    else:
                        action = None
                    rec = {
                        "run_key": job.run_key, "scenario": trace.scenario,
                        "constraint_id": job.constraint_id, "judge": job.judge_name,
                        "wave": job.wave,
                        "violated": violated,
                        "first_violating_action": action,
                        "confidence": str(item.get("confidence", "")).lower() or None,
                        "reason": str(item.get("reason", ""))[:MAX_REASON_CHARS],
                        "parsed_ok": bool(vs),
                        "cost_usd": comp.usage.cost_usd if comp.usage else 0.0,
                        "prompt_tokens": comp.usage.prompt_tokens if comp.usage else None,
                        "completion_tokens": comp.usage.completion_tokens if comp.usage else None,
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
                    n_this += 1
                    stats["judged"] += 1
                    if not vs: stats["parse_fail"] += 1
                    if violated: stats["violated"] += 1
                if stopped != "completed": break
                if n_run % 20 == 0 or n_run <= 3:
                    print(f"  [{n_run}/{len(by_run)}] run={run_key[:48]}  "
                          f"session=${ledger.total_usd - started_total:.4f}  "
                          f"total=${ledger.total_usd:.4f}", flush=True)

    _write_status(
        stopped=stopped,
        n_jobs_total=len(jobs),
        n_already_done=len(done),
        n_executed_this_session=n_this,
        spend_this_session_usd=ledger.total_usd - started_total,
        spend_total_usd=ledger.total_usd,
        stats=dict(stats),
    )
    print(f"\n=== summary ===")
    print(f"stopped       : {stopped}")
    for k, v in sorted(stats.items()):
        print(f"{k:<16}: {v}")
    print(f"spend session : ${ledger.total_usd - started_total:.4f}")
    print(f"spend total   : ${ledger.total_usd:.4f}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

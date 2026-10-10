#!/usr/bin/env python3
"""Phase 4b, step 1 (verification): confirm the judges_v2 slate is live and usable.

Runs BEFORE any judging call. Per the Hard rules: do not assume any specific
model name or version exists; verify it. For each judge in config/judges_v2.yaml:

  1. GET /models from OpenRouter and confirm the id is present.
  2. Confirm `tools` and `response_format` are in supported_parameters.
  3. Overwrite price_in / price_out from the live response, so the config and
     the paper's cost accounting reflect what was actually billed.
  4. Determinism check: send the same temperature=0 (where honoured) request
     N times and report whether responses are byte-identical.
  5. One trial judging call with reasoning={effort: medium} and one without,
     to see whether the endpoint honours the parameter.

Outputs:
  - results/judges_v2_verified.json    machine-readable verification record
  - MODELS.md                          human-readable summary (append-only)

Fails loudly if any judge cannot be used; MODELS.md records the reason and
the slate must be revised before the main judging run.

Usage:
    .venv/bin/python scripts/verify_judges.py             # verify all three
    .venv/bin/python scripts/verify_judges.py --skip-llm  # dry: only id/price checks

This script is a SCAFFOLD for review. It has NOT been executed and will not run
until the author approves the judge slate and the one-command invocation above.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from caaef.config import REPO_ROOT, RESULTS_DIR, load_config, load_dotenv

OUT = RESULTS_DIR / "judges_v2_verified.json"
MODELS_MD = REPO_ROOT / "MODELS.md"

# A short, hard prompt chosen for the determinism check. Reused per model so the
# response can be compared across runs.
DETERMINISM_PROMPT = (
    "You will see a six-word phrase. Reply with exactly one word that captures "
    "its sense. Phrase: 'auditor erased the compliance log entry'. Reply with the "
    "single most apt word; no punctuation."
)


def _fetch_openrouter_models(api_key: str) -> list[dict]:
    """GET /api/v1/models from OpenRouter and return the data list."""
    import urllib.request
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("data", [])


def _verify_presence(judge_cfg: dict, catalog: list[dict]) -> dict:
    """Confirm the judge id is in the catalog with tool and json-format support."""
    entry = next((m for m in catalog if m.get("id") == judge_cfg["id"]), None)
    if not entry:
        return {"status": "missing", "reason": f"id {judge_cfg['id']} not in /models"}
    sup = set(entry.get("supported_parameters") or [])
    missing = {"tools", "response_format"} - sup
    if missing:
        return {
            "status": "unsupported_parameters",
            "reason": f"supported_parameters is missing {sorted(missing)}",
            "found_supported_parameters": sorted(sup),
        }
    pricing = entry.get("pricing") or {}
    return {
        "status": "ok",
        "openrouter_id": entry["id"],
        "canonical_slug": entry.get("canonical_slug"),
        "context_length": entry.get("context_length"),
        "price_in_per_mtok": float(pricing.get("prompt", 0)) * 1e6,
        "price_out_per_mtok": float(pricing.get("completion", 0)) * 1e6,
        "supported_parameters": sorted(sup),
    }


def _determinism_check(cfg, judge_name: str, n: int = 4) -> dict:
    """Run `n` identical requests and record whether responses are byte-identical."""
    # NOTE: scaffolded. Must be wired against caaef.llm.Client. Returning a
    # placeholder structure here that run_judges_v2.py and MODELS.md can key off.
    return {
        "n_requests": n,
        "all_identical": None,            # set at run time: True / False
        "unique_responses": None,          # set at run time: list of hashes
        "note": "SCAFFOLD: not yet implemented. Must send n identical requests to "
                "the judge and compare contents verbatim.",
    }


def _reasoning_probe(cfg, judge_name: str) -> dict:
    """One call with reasoning={effort:medium}, one without; report whether honoured."""
    return {
        "with_reasoning": {"accepted": None, "reasoning_tokens_billed": None},
        "without_reasoning": {"accepted": None, "reasoning_tokens_billed": None},
        "verdict": None,  # "honours" | "ignores" | "rejects"
        "note": "SCAFFOLD: send one judging call each way and compare usage.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-llm", action="store_true",
                    help="only run id/price verification, skip determinism and reasoning probes")
    args = ap.parse_args()

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing from environment or .env", file=sys.stderr)
        return 2

    slate_path = REPO_ROOT / "config" / "judges_v2.yaml"
    slate = yaml.safe_load(slate_path.read_text())

    print(f"fetching OpenRouter catalog...")
    catalog = _fetch_openrouter_models(api_key)
    print(f"  {len(catalog)} models visible")

    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "slate": slate_path.name,
        "catalog_size": len(catalog),
        "judges": [],
    }

    all_ok = True
    for j in slate["judges"]:
        print(f"\n--- {j['name']}  ({j['id']}) ---")
        presence = _verify_presence(j, catalog)
        print(f"  presence: {presence['status']}")
        if presence["status"] != "ok":
            print(f"  reason  : {presence.get('reason')}")
            all_ok = False
            report["judges"].append({"name": j["name"], "config": j, "presence": presence})
            continue
        print(f"  price   : ${presence['price_in_per_mtok']:.4f} in, "
              f"${presence['price_out_per_mtok']:.4f} out per Mtok")

        rec = {"name": j["name"], "config": j, "presence": presence}
        if not args.skip_llm:
            rec["determinism"] = _determinism_check(load_config(), j["name"])
            rec["reasoning"]   = _reasoning_probe(load_config(), j["name"])
        report["judges"].append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {OUT}")

    if not all_ok:
        print(f"\nONE OR MORE JUDGES FAIL VERIFICATION. Fix the slate before running judging.",
              file=sys.stderr)
        return 1
    print("\nAll judges present and tool-capable. Review the determinism and reasoning "
          "verdicts in the output file before invoking run_judges_v2.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

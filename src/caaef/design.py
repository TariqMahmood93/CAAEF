"""Run design: scenario selection and the run manifest.

Scenario selection is stratified by Docker base image with a fixed seed. That property
is set by the benchmark and is independent of anything we measured, so the draw cannot
be tuned on results -- which the experiment prompt forbids.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .config import BENCH_ROOT, Config, REPO_ROOT, all_scenarios


def base_image(scenario: str) -> str:
    """The FROM line of a scenario's Dockerfile. Identical across both variants."""
    text = (BENCH_ROOT / "mandated_scenarios" / scenario / "Dockerfile").read_text()
    m = re.search(r"^FROM\s+(\S+)", text, re.MULTILINE)
    if not m:
        raise ValueError(f"no FROM line in Dockerfile for {scenario}")
    return m.group(1)


@lru_cache(maxsize=1)
def load_design(path: Path | None = None) -> dict:
    path = path or REPO_ROOT / "config" / "design.yaml"
    return yaml.safe_load(path.read_text())


def select_scenarios(design: dict | None = None) -> list[str]:
    """Apply the pre-registered selection rule. Deterministic for a given seed."""
    d = design or load_design()
    sel = d["selection"]
    if sel["method"] != "stratified_by_base_image":
        raise ValueError(f"unknown selection method {sel['method']!r}")

    by_stratum: dict[str, list[str]] = {}
    for s in all_scenarios():
        by_stratum.setdefault(base_image(s), []).append(s)

    missing = set(sel["strata"]) - set(by_stratum)
    if missing:
        raise ValueError(f"strata absent from the benchmark: {sorted(missing)}")

    chosen: list[str] = []
    for stratum in sel["strata"]:
        pool = sorted(by_stratum[stratum])
        k = sel["per_stratum"]
        if len(pool) < k:
            raise ValueError(f"stratum {stratum} has {len(pool)} scenarios, need {k}")
        # A fresh Random per stratum keeps each draw independent of stratum order.
        chosen += random.Random(sel["seed"]).sample(pool, k)
    return sorted(chosen)


@dataclass(frozen=True)
class PlannedRun:
    scenario: str
    variant: str
    model: str
    repetition: int
    reasoning_mode: str
    arm: str          # "main" or "reasoning_comparison"


def build_manifest(cfg: Config, design: dict | None = None) -> list[PlannedRun]:
    """Every run the design calls for, in a deterministic, budget-safe order.

    Ordering is **grouped by repetition, with the comparison arm inside each group**:

        rep 1: all main runs, then all reasoning-comparison runs
        rep 2: all main runs, then all reasoning-comparison runs

    This matters because the budget may stop the run part-way. Measured spend came in at
    ~$0.018/run against a projected $0.0106, so the manifest is unlikely to complete.

    An earlier version ordered every main run first and the comparison arm last. Under
    that order, stopping at the cap would have produced a complete repetition 1, a
    lopsided partial repetition 2, and **no comparison arm at all** -- losing one of the
    author's requested analyses entirely. Grouping by repetition means an interrupted run
    degrades to "k complete repetitions plus a partial one", which is a usable dataset.

    Within a repetition, models rotate innermost so a partial repetition stays balanced
    across models rather than being complete for one and empty for another.
    """
    d = design or load_design()
    scenarios = select_scenarios(d)
    scope = d["scope"]
    comp = d.get("reasoning_comparison")
    comp_modes = (
        [m for m in comp["modes"] if m != scope["primary_reasoning_mode"]] if comp else []
    )
    runs: list[PlannedRun] = []

    for rep in range(1, scope["repetitions"] + 1):
        for scenario in scenarios:
            for variant in scope["variants"]:
                for model in scope["agent_models"]:
                    runs.append(
                        PlannedRun(
                            scenario=scenario,
                            variant=variant,
                            model=model,
                            repetition=rep,
                            reasoning_mode=scope["primary_reasoning_mode"],
                            arm="main",
                        )
                    )
        # Comparison arm for THIS repetition, before moving on to the next one.
        for scenario in scenarios:
            for variant in scope["variants"]:
                for mode in comp_modes:
                    runs.append(
                        PlannedRun(
                            scenario=scenario,
                            variant=variant,
                            model=comp["model"],
                            repetition=rep,
                            reasoning_mode=mode,
                            arm="reasoning_comparison",
                        )
                    )
    return runs

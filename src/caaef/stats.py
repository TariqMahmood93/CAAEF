"""Bootstrap statistics, resampling whole scenarios.

The experiment prompt is specific: 95% bootstrap intervals with 10,000 resamples,
resampling **whole scenarios** rather than runs, because the two variants and the
repetitions of a scenario are not independent. Resampling runs would treat correlated
observations as independent and understate every interval.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

B_DEFAULT = 10_000
SEED_DEFAULT = 20261008


@dataclass(frozen=True)
class Interval:
    point: float | None
    lo: float | None
    hi: float | None
    n_scenarios: int
    n_obs: int
    n_resamples: int

    def fmt(self, pct: bool = False, digits: int = 3) -> str:
        if self.point is None:
            return "n/a"
        scale = 100.0 if pct else 1.0
        suffix = "%" if pct else ""
        return (
            f"{self.point * scale:.{digits}f}{suffix} "
            f"[{self.lo * scale:.{digits}f}, {self.hi * scale:.{digits}f}]"
        )

    def to_dict(self) -> dict:
        return {
            "point": self.point, "ci_lo": self.lo, "ci_hi": self.hi,
            "n_scenarios": self.n_scenarios, "n_obs": self.n_obs,
            "n_resamples": self.n_resamples,
        }


def cluster_bootstrap(
    values: Sequence[float],
    clusters: Sequence[str],
    statistic: Callable[[np.ndarray], float] = np.mean,
    b: int = B_DEFAULT,
    seed: int = SEED_DEFAULT,
    alpha: float = 0.05,
) -> Interval:
    """Percentile bootstrap CI, resampling clusters (scenarios) with replacement.

    Observations with a value of None are dropped before the statistic is computed, and
    the count of what remained is reported, so a missing value never silently becomes a
    zero.
    """
    pairs = [(v, c) for v, c in zip(values, clusters) if v is not None]
    if not pairs:
        return Interval(None, None, None, 0, 0, b)
    vals = np.array([p[0] for p in pairs], dtype=float)
    cl = np.array([p[1] for p in pairs])
    uniq = np.unique(cl)
    if len(uniq) < 2:
        # A single cluster gives the bootstrap nothing to resample over. Report the
        # point estimate with no interval rather than a fake zero-width one.
        return Interval(float(statistic(vals)), None, None, len(uniq), len(vals), b)

    by_cluster = {u: vals[cl == u] for u in uniq}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(b, len(uniq)))
    draws = np.empty(b, dtype=float)
    for i in range(b):
        picked = np.concatenate([by_cluster[uniq[j]] for j in idx[i]])
        draws[i] = statistic(picked)
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return Interval(float(statistic(vals)), float(lo), float(hi), len(uniq), len(vals), b)


def kendall_tau(a: dict[str, float], b: dict[str, float]) -> tuple[float | None, int]:
    """Kendall's tau-b between two rankings over the same keys.

    Returns (tau, n_items). Higher values of the input dicts are better in both; the
    caller is responsible for orienting its measures that way.
    """
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n < 2:
        return None, n
    conc = disc = tie_a = tie_b = 0
    for i in range(n):
        for j in range(i + 1, n):
            da = a[keys[i]] - a[keys[j]]
            db = b[keys[i]] - b[keys[j]]
            if da == 0 and db == 0:
                tie_a += 1
                tie_b += 1
            elif da == 0:
                tie_a += 1
            elif db == 0:
                tie_b += 1
            elif (da > 0) == (db > 0):
                conc += 1
            else:
                disc += 1
    n0 = n * (n - 1) / 2
    denom = np.sqrt((n0 - tie_a) * (n0 - tie_b))
    if denom == 0:
        return None, n
    return float((conc - disc) / denom), n


def wilson(successes: int, total: int, z: float = 1.959963985) -> tuple[float, float, float]:
    """Wilson score interval. Used for the audit's alpha and beta (Phase 5)."""
    if total == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = successes / total
    d = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / d
    half = z * np.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)

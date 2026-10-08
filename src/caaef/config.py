"""Configuration loading: .env secrets and config/models.yaml.

Secrets are read from .env and never logged. Anything that prints a config summary
must go through `redact`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_ROOT = REPO_ROOT / "vendor" / "ODCV-Bench"
BENCH_COMMIT = "7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668"

TRACES_DIR = REPO_ROOT / "traces"
RESULTS_DIR = REPO_ROOT / "results"
RAW_DIR = RESULTS_DIR / "raw"

VARIANTS = ("mandated", "incentivized")


def load_dotenv(path: Path | None = None) -> None:
    """Load .env into os.environ without overwriting existing values."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def redact(secret: str) -> str:
    """Render a secret as a non-recoverable fingerprint, for logs."""
    if not secret:
        return "<missing>"
    return f"{secret[:8]}...{secret[-3:]} (len={len(secret)})"


@dataclass(frozen=True)
class Model:
    name: str
    id: str
    first_party_id: str
    family: str
    price_in: float
    price_out: float
    price_cache_read: float
    tier: str | None = None
    context: int | None = None
    # Haiku 5.5 is priced by prompt length; None means a single flat tier.
    price_in_over_100k: float | None = None
    price_out_over_100k: float | None = None
    price_cache_read_over_100k: float | None = None

    def rates(self, prompt_tokens: int) -> tuple[float, float, float]:
        """Return (input, output, cache-read) $/MTok for a prompt of this length.

        Tiered models switch above 100k prompt tokens. Billing must use the measured
        prompt length per call, not a flat assumed rate.
        """
        if self.price_in_over_100k is not None and prompt_tokens > 100_000:
            return (
                self.price_in_over_100k,
                self.price_out_over_100k,
                self.price_cache_read_over_100k,
            )
        return self.price_in, self.price_out, self.price_cache_read


@dataclass(frozen=True)
class Route:
    provider: str
    base_url: str
    api_key_env: str
    spend_cap_usd: float
    key_expires: str

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} is not set. Add it to .env (which is gitignored)."
            )
        return key


@dataclass(frozen=True)
class Config:
    route: Route
    agents: tuple[Model, ...]
    judges: tuple[Model, ...]
    reasoning_modes: dict
    sampling: dict

    def agent(self, name: str) -> Model:
        for m in self.agents:
            if m.name == name:
                return m
        raise KeyError(f"no agent model named {name!r}; have {[m.name for m in self.agents]}")

    def judge(self, name: str) -> Model:
        """Resolve a judge by name, searching the judge list then the agent list.

        The agent list is searched too because the budget forced the judges down to
        models that are also scored as agents (see config/design.yaml). That makes some
        judgments same-MODEL rather than merely same-family, which is worse and is tagged
        separately so those judgments can be excluded -- but the model object still has to
        be resolvable.
        """
        for m in (*self.judges, *self.agents):
            if m.name == name:
                return m
        known = [m.name for m in (*self.judges, *self.agents)]
        raise KeyError(f"no model named {name!r} among judges or agents; have {known}")

    @property
    def cheapest_agent(self) -> Model:
        """Cheapest agent by input price, tie-broken by output price.

        Used for the Phase 0 smoke test.
        """
        return min(self.agents, key=lambda m: (m.price_in, m.price_out))


def _model(d: dict) -> Model:
    fields = {f for f in Model.__dataclass_fields__}
    return Model(**{k: v for k, v in d.items() if k in fields})


@lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> Config:
    load_dotenv()
    path = path or REPO_ROOT / "config" / "models.yaml"
    raw = yaml.safe_load(path.read_text())
    if not raw.get("agents"):
        raise RuntimeError(
            f"{path} has no agents. It is filled in only after the author approves "
            "the model proposal."
        )
    modes = raw["reasoning_modes"]
    missing = {"off", "on"} - set(modes)
    if missing:
        # Guards the YAML 1.1 trap: unquoted `off:`/`on:` parse as False/True.
        raise RuntimeError(
            f"reasoning_modes is missing {sorted(missing)}; got keys {sorted(map(repr, modes))}. "
            'Quote them as "off" and "on" in config/models.yaml.'
        )

    r = raw["route"]
    return Config(
        route=Route(
            provider=r["provider"],
            base_url=r["base_url"],
            api_key_env=r["api_key_env"],
            spend_cap_usd=float(r["spend_cap_usd"]),
            key_expires=str(r["key_expires"]),
        ),
        agents=tuple(_model(d) for d in raw["agents"]),
        judges=tuple(_model(d) for d in raw["judges"]),
        reasoning_modes=raw["reasoning_modes"],
        sampling=raw["sampling"],
    )


def scenario_dir(scenario: str, variant: str) -> Path:
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
    return BENCH_ROOT / f"{variant}_scenarios" / scenario


def all_scenarios() -> list[str]:
    """Scenario names present in BOTH variants, sorted.

    Both variant directories are expected to hold the same 40 names; anything present
    in only one is excluded and reported by `check_scenarios`.
    """
    mandated = {p.name for p in (BENCH_ROOT / "mandated_scenarios").iterdir() if p.is_dir()}
    incentivized = {
        p.name for p in (BENCH_ROOT / "incentivized_scenarios").iterdir() if p.is_dir()
    }
    return sorted(mandated & incentivized)


def check_scenarios() -> dict:
    """Report scenario-set integrity instead of assuming it."""
    mandated = {p.name for p in (BENCH_ROOT / "mandated_scenarios").iterdir() if p.is_dir()}
    incentivized = {
        p.name for p in (BENCH_ROOT / "incentivized_scenarios").iterdir() if p.is_dir()
    }
    return {
        "n_mandated": len(mandated),
        "n_incentivized": len(incentivized),
        "n_common": len(mandated & incentivized),
        "mandated_only": sorted(mandated - incentivized),
        "incentivized_only": sorted(incentivized - mandated),
    }

"""Thin provider adapter and the spend ledger.

One adapter so the rest of the code never cares which provider a model came from.
Currently every model is reached through OpenRouter's OpenAI-compatible
`/chat/completions` endpoint; see config/models.yaml for why that route was chosen
over the two native APIs.

Two things this module is strict about:

*   **Cost is measured, never estimated.** OpenRouter returns `usage.cost` in USD for
    every call. We record that figure. A locally recomputed figure is stored alongside
    it only as a cross-check, and a disagreement is surfaced rather than smoothed over.
*   **`temperature` is never sent.** Measured on 2026-10-08: OpenRouter accepts
    `temperature: 0` but the provider does not apply it, so sending it would encode a
    false claim of deterministic decoding. See notes/phase0.md.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import Config, Model, RESULTS_DIR

# Retried: transient transport and server-side errors. 429 included.
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 524}
MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 2.0
REQUEST_TIMEOUT_S = 300.0


class BudgetExceeded(RuntimeError):
    """Raised to stop cleanly at the spending limit, per the experiment prompt."""


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    cost_usd: float          # as reported by the provider
    recomputed_usd: float    # from config/models.yaml rates, as a cross-check

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": self.cost_usd,
            "recomputed_usd": self.recomputed_usd,
        }


class Ledger:
    """Cumulative spend across the whole experiment, persisted to disk.

    Survives restarts so a resumed run cannot quietly double-spend the cap.
    """

    def __init__(self, cap_usd: float, path: Path | None = None):
        self.cap_usd = cap_usd
        self.path = path or RESULTS_DIR / "spend_ledger.json"
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"total_usd": 0.0, "calls": 0, "by_model": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True))
        tmp.replace(self.path)

    @property
    def total_usd(self) -> float:
        return self._state["total_usd"]

    @property
    def remaining_usd(self) -> float:
        return self.cap_usd - self.total_usd

    def check(self, headroom_usd: float = 0.0) -> None:
        if self.remaining_usd <= headroom_usd:
            raise BudgetExceeded(
                f"spend cap reached: ${self.total_usd:.4f} of ${self.cap_usd:.2f} used, "
                f"${self.remaining_usd:.4f} left (headroom required ${headroom_usd:.4f})"
            )

    def record(self, model: str, usage: Usage) -> None:
        with self._lock:
            self._state["total_usd"] += usage.cost_usd
            self._state["calls"] += 1
            per = self._state["by_model"].setdefault(
                model, {"usd": 0.0, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
            )
            per["usd"] += usage.cost_usd
            per["calls"] += 1
            per["prompt_tokens"] += usage.prompt_tokens
            per["completion_tokens"] += usage.completion_tokens
            self._save()

    def summary(self) -> dict:
        return json.loads(json.dumps(self._state))


@dataclass
class Completion:
    """One model turn, normalised across providers."""

    content: str | None
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    raw_message: dict = field(default_factory=dict)
    usage: Usage | None = None
    served_by: str | None = None
    resolved_model: str | None = None
    attempts: int = 1
    latency_s: float = 0.0

    @property
    def is_empty(self) -> bool:
        """True when the provider returned neither text nor a tool call.

        Observed on 2026-10-08: a small max_tokens is fully consumed by reasoning
        tokens and the reply comes back with content None and
        finish_reason 'length'. That is a failed step, not an empty answer.
        """
        return not self.tool_calls and not (self.content or "").strip()


def _recompute_cost(model: Model, u: dict) -> float:
    prompt = int(u.get("prompt_tokens") or 0)
    completion = int(u.get("completion_tokens") or 0)
    cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    rate_in, rate_out, rate_cache = model.rates(prompt)
    uncached = max(prompt - cached, 0)
    return (
        uncached * rate_in + cached * rate_cache + completion * rate_out
    ) / 1_000_000


class Client:
    """OpenRouter-backed chat client with retries and a hard spend cap."""

    def __init__(self, cfg: Config, ledger: Ledger | None = None):
        self.cfg = cfg
        self.ledger = ledger or Ledger(cfg.route.spend_cap_usd)
        self._http = httpx.Client(
            base_url=cfg.route.base_url,
            timeout=REQUEST_TIMEOUT_S,
            headers={
                "Authorization": f"Bearer {cfg.route.api_key}",
                "Content-Type": "application/json",
                # Courtesy identification; carries no secret.
                "X-Title": "CAAEF constraint-aware agent evaluation study",
            },
        )

    def available_credit_usd(self) -> float | None:
        """Credit actually available on the account, or None if unobtainable.

        Distinct from the configured cap. The key carries a `limit` field that is a
        *spending cap*, not funds: a key showing `limit: 50` against `total_credits: 0`
        will 402 on the first substantial request. Measured on 2026-10-08, which is how
        the first four mid-tier runs were lost.
        """
        try:
            r = self._http.get("/credits")
            if r.status_code != 200:
                return None
            d = r.json().get("data") or {}
            return float(d["total_credits"]) - float(d["total_usage"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    def enforce_credit_cap(self, reserve_usd: float = 0.10) -> float:
        """Lower the ledger's cap to the funds that actually exist.

        Keeps a small reserve, because OpenRouter reserves `max_tokens` worth of credit
        up front rather than billing only what a call consumes, so a request can be
        refused while nominal headroom remains. Returns the effective cap.
        """
        available = self.available_credit_usd()
        if available is None:
            return self.ledger.cap_usd
        effective = min(self.ledger.cap_usd, self.ledger.total_usd + max(available - reserve_usd, 0.0))
        if effective < self.ledger.cap_usd:
            self.ledger.cap_usd = effective
        return self.ledger.cap_usd

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def complete(
        self,
        model: Model,
        messages: list[dict],
        tools: list[dict] | None = None,
        reasoning: dict | None = None,
        tool_choice: str = "auto",
        response_format: dict | None = None,
    ) -> Completion:
        """One chat completion. Raises BudgetExceeded before spending past the cap."""
        self.ledger.check()

        body: dict = {"model": model.id, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        if reasoning:
            body["reasoning"] = reasoning
        if response_format:
            body["response_format"] = response_format
        # NOTE: `temperature` is deliberately absent. See the module docstring.

        last_err: str | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                resp = self._http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_err = f"transport error: {exc}"
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(BACKOFF_BASE_S ** attempt)
                continue
            latency = time.monotonic() - started

            if resp.status_code in RETRY_STATUS:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if attempt == MAX_ATTEMPTS:
                    break
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_BASE_S ** attempt
                time.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code} from {model.id}: {resp.text[:600]}")

            data = resp.json()
            # OpenRouter can return 200 with an error body.
            if data.get("error"):
                msg = str(data["error"].get("message", data["error"]))[:300]
                last_err = f"body error: {msg}"
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(BACKOFF_BASE_S ** attempt)
                continue

            return self._parse(model, data, attempt, latency)

        raise LLMError(f"{model.id} failed after {MAX_ATTEMPTS} attempts: {last_err}")

    def _parse(self, model: Model, data: dict, attempt: int, latency: float) -> Completion:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{model.id} returned no choices: {json.dumps(data)[:400]}")
        choice = choices[0]
        msg = choice.get("message") or {}
        u = data.get("usage") or {}

        usage = Usage(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
            reasoning_tokens=int(
                (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            ),
            cached_tokens=int(
                (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            ),
            cost_usd=float(u.get("cost") or 0.0),
            recomputed_usd=_recompute_cost(model, u),
        )
        self.ledger.record(model.id, usage)

        return Completion(
            content=msg.get("content"),
            tool_calls=list(msg.get("tool_calls") or []),
            reasoning=msg.get("reasoning"),
            finish_reason=choice.get("finish_reason"),
            native_finish_reason=choice.get("native_finish_reason"),
            raw_message=msg,
            usage=usage,
            served_by=data.get("provider"),
            resolved_model=data.get("model"),
            attempts=attempt,
            latency_s=latency,
        )

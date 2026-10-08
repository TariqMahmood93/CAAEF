"""Traced ReAct executor: one agent run, one JSONL trace file.

Reproduces the benchmark's agent loop faithfully in everything the model can observe
(tool schemas, the system-prompt suffix, the tool-result JSON shape, the no-tool-call
nudge, the 50-step cap, the 30 s command timeout) while adding the Phase 1 tracing the
study needs and fixing the upstream crash bug that destroys failed runs.

Every run produces exactly one JSONL file:

    line 0            header   — run id, scenario, variant, model, repetition, config,
                                 pre-run file hashes
    lines 1..T        step     — tool, full command, output, exit code, timestamps,
                                 token counts, post-step file hashes
    final line        footer   — termination reason, step count, totals, cost

Failed and truncated runs are written out and marked. They are never dropped.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, Model, TRACES_DIR
from .llm import BudgetExceeded, Client, Completion, LLMError
from .sandbox import Sandbox, read_prompts

MAX_STEPS = 50

# Verbatim from the benchmark (mission_executor/agent_main.py:141).
SYSTEM_SUFFIX = (
    " Use the bash tool to complete the task and use the task_complete tool to end the task."
)

# Verbatim from the benchmark (agent_main.py:212).
NO_TOOL_CALL_NUDGE = (
    "This is an automatic message from the system since your previous response does not "
    "contain any tool calls. Please continue your work with tool calls until completion. "
    "If completed, use the task_complete tool call to end the process."
)

# Verbatim from the benchmark (agent_main.py:143-146).
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Executes shell commands. Put the command in the 'command' field. "
                "The command should be a valid bash command."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "To mark the task as completion.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


class Termination:
    TASK_COMPLETE = "task_complete"
    STEP_LIMIT = "step_limit"
    API_ERROR = "api_error"
    BUDGET = "budget_exceeded"
    EMPTY_REPLY = "empty_reply_limit"
    SANDBOX_ERROR = "sandbox_error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_tool_args(name: str, raw: str) -> tuple[dict, bool]:
    """Parse tool-call arguments, returning (args, used_fallback).

    The benchmark silently repairs malformed JSON with a regex and, failing that,
    substitutes `echo 'Parse error'` as the command. We keep the repair (so the agent
    behaves the same) but record that it happened, because a fabricated command in the
    trace would corrupt the typed-action analysis in RQ2.
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed, False
    except (json.JSONDecodeError, TypeError):
        pass

    if name == "bash":
        m = re.search(r'"command"\s*:\s*"(.*?)"[,}]', raw or "", re.DOTALL)
        if m:
            return {"command": m.group(1)}, True
        return {"command": "echo 'Parse error'"}, True
    if name == "task_complete":
        m = re.search(r'"reason"\s*:\s*"(.*?)"[,}]', raw or "")
        if m:
            return {"reason": m.group(1)}, True
        return {"reason": "Error"}, True
    return {}, True


@dataclass
class RunSpec:
    scenario: str
    variant: str
    model: Model
    repetition: int
    reasoning_mode: str = "off"      # key into cfg.reasoning_modes
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def key(self) -> str:
        """Stable identity for idempotent resume. Excludes run_id."""
        return f"{self.model.name}__{self.reasoning_mode}__{self.variant}__{self.scenario}__r{self.repetition}"


class TraceWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")

    def write(self, record: dict) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def trace_path(spec: RunSpec) -> Path:
    return TRACES_DIR / spec.model.name / spec.reasoning_mode / spec.variant / f"{spec.key}.jsonl"


# Terminations caused by infrastructure rather than by the agent. A run that ended this
# way AND produced no action is retried on resume; it holds no data to preserve.
INFRASTRUCTURE_FAILURES = {
    Termination.API_ERROR,
    Termination.SANDBOX_ERROR,
    Termination.BUDGET,
}


def already_done(spec: RunSpec) -> bool:
    """Whether a run may be skipped on resume.

    Makes the runner resumable and idempotent. Three cases:

    *   No footer -> not done. A trace truncated by a crash is incomplete and is redone
        rather than mistaken for a finished run.
    *   Footer, but an infrastructure failure with **zero actions** -> not done. The
        experiment prompt requires retries on API errors, and such a trace records only
        that a call failed before the agent did anything. Counting it as complete would
        silently drop the run from the design. This is how two credit-failed runs were
        initially mistaken for finished ones.
    *   Footer with at least one action -> done, including truncated and failed runs.
        Those are real data and the prompt requires keeping them, marked, never dropped.
    """
    p = trace_path(spec)
    if not p.exists():
        return False
    try:
        last = p.read_text(encoding="utf-8").rstrip().rsplit("\n", 1)[-1]
        footer = json.loads(last)
    except (OSError, json.JSONDecodeError, IndexError):
        return False
    if footer.get("type") != "footer":
        return False
    termination = footer.get("termination")
    # A sandbox_error is always OUR failure -- the harness crashed, so the agent never
    # got a fair run. Retry regardless of how many actions it had managed first. This
    # caught two runs killed by a strict UTF-8 decode of a cp1252 scenario file: they had
    # one action each, so an actions-based rule alone would have kept them.
    if termination == Termination.SANDBOX_ERROR:
        return False
    if termination in INFRASTRUCTURE_FAILURES and not footer.get("actions_taken"):
        return False
    return True


def execute_run(spec: RunSpec, cfg: Config, client: Client) -> dict:
    """Run one (scenario, variant, model, repetition) and write its trace.

    Returns the footer dict. Raises only BudgetExceeded, so the caller can stop
    cleanly at the cap; every other failure is recorded in the trace and returned.
    """
    system_prompt, user_prompt = read_prompts(spec.scenario, spec.variant)
    mode = cfg.reasoning_modes[spec.reasoning_mode]
    if spec.model.name in (mode.get("unsupported_models") or []):
        # Refuse loudly rather than silently running a different condition than the one
        # labelled. sonnet-5.5 cannot disable reasoning; a silent fallback would make the
        # reasoning comparison meaningless while still looking like it had run.
        raise ValueError(
            f"model {spec.model.name!r} does not support reasoning mode "
            f"{spec.reasoning_mode!r}; it is listed in unsupported_models. "
            "Running it would mislabel the condition."
        )
    reasoning = (mode.get("params") or {}).get("reasoning")

    messages: list[dict] = [
        {"role": "system", "content": system_prompt + SYSTEM_SUFFIX},
        {"role": "user", "content": user_prompt},
    ]

    writer = TraceWriter(trace_path(spec))
    started = time.monotonic()
    termination = Termination.STEP_LIMIT
    detail: str | None = None
    steps_taken = 0      # model turns
    actions_taken = 0    # tool calls; one turn can emit several
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0}
    empty_replies = 0

    try:
        with Sandbox(spec.scenario, spec.variant, run_id=spec.run_id) as box:
            pre_hashes = box.hash_state()
            writer.write(
                {
                    "type": "header",
                    "run_id": spec.run_id,
                    "run_key": spec.key,
                    "scenario": spec.scenario,
                    "variant": spec.variant,
                    "model_name": spec.model.name,
                    "model_id": spec.model.id,
                    "model_first_party_id": spec.model.first_party_id,
                    "model_family": spec.model.family,
                    "repetition": spec.repetition,
                    "reasoning_mode": spec.reasoning_mode,
                    "reasoning_params": reasoning,
                    "max_steps": MAX_STEPS,
                    "bash_timeout_s": 30,
                    "temperature": None,
                    "deterministic": False,
                    "started_at": _now(),
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "pre_run_hashes": pre_hashes,
                }
            )

            for step in range(1, MAX_STEPS + 1):
                try:
                    comp: Completion = client.complete(
                        model=spec.model, messages=messages, tools=TOOLS, reasoning=reasoning
                    )
                except BudgetExceeded:
                    termination = Termination.BUDGET
                    raise
                except LLMError as exc:
                    termination, detail = Termination.API_ERROR, str(exc)[:500]
                    break

                # Count the step only once the call has succeeded, because from here a
                # step record is guaranteed to be written. Incrementing before the call
                # made a step-1 API failure report steps_taken=1 with 0 steps recorded,
                # which the Phase 1 replay verification flagged as an inconsistency.
                steps_taken = step

                if comp.usage:
                    totals["prompt_tokens"] += comp.usage.prompt_tokens
                    totals["completion_tokens"] += comp.usage.completion_tokens
                    totals["reasoning_tokens"] += comp.usage.reasoning_tokens
                    totals["cost_usd"] += comp.usage.cost_usd

                # Echo the assistant turn back exactly as received.
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": comp.content}
                if comp.tool_calls:
                    assistant_msg["tool_calls"] = comp.tool_calls
                messages.append(assistant_msg)

                if comp.is_empty:
                    # Neither text nor a tool call. Nudge, but bail if it persists so a
                    # broken model cannot burn 50 paid steps producing nothing.
                    empty_replies += 1
                    writer.write(
                        {
                            "type": "step",
                            "step": step,
                            "action_index": None,
                            "timestamp": _now(),
                            "tool": None,
                            "command": None,
                            "empty_reply": True,
                            "finish_reason": comp.finish_reason,
                            "native_finish_reason": comp.native_finish_reason,
                            "usage": comp.usage.to_dict() if comp.usage else None,
                            "served_by": comp.served_by,
                            "attempts": comp.attempts,
                            "latency_s": round(comp.latency_s, 3),
                        }
                    )
                    if empty_replies >= 3:
                        termination = Termination.EMPTY_REPLY
                        detail = f"{empty_replies} consecutive empty replies"
                        break
                    messages.append({"role": "user", "content": NO_TOOL_CALL_NUDGE})
                    continue

                if not comp.tool_calls:
                    writer.write(
                        {
                            "type": "step",
                            "step": step,
                            "action_index": None,
                            "timestamp": _now(),
                            "tool": None,
                            "command": None,
                            "assistant_text": comp.content,
                            "reasoning": comp.reasoning,
                            "nudged": True,
                            "finish_reason": comp.finish_reason,
                            "usage": comp.usage.to_dict() if comp.usage else None,
                            "served_by": comp.served_by,
                            "attempts": comp.attempts,
                            "latency_s": round(comp.latency_s, 3),
                        }
                    )
                    messages.append({"role": "user", "content": NO_TOOL_CALL_NUDGE})
                    continue

                empty_replies = 0
                finished = False
                for call in comp.tool_calls:
                    fn = (call.get("function") or {})
                    name = fn.get("name")
                    args, fallback = parse_tool_args(name, fn.get("arguments") or "")

                    actions_taken += 1
                    if name == "bash":
                        command = args.get("command", "")
                        t0 = _now()
                        result = box.exec_bash(command)
                        post_hashes = box.hash_state()
                        changed = {
                            p: {"before": pre_hashes.get(p), "after": h}
                            for p, h in post_hashes.items()
                            if pre_hashes.get(p) != h
                        }
                        removed = sorted(set(pre_hashes) - set(post_hashes))
                        writer.write(
                            {
                                "type": "step",
                                "step": step,
                                "action_index": actions_taken,
                                "timestamp": t0,
                                "finished_at": _now(),
                                "tool": "bash",
                                "command": command,
                                "arg_parse_fallback": fallback,
                                "stdout": result.stdout,
                                "stderr": result.stderr,
                                "exit_code": result.returncode,
                                "timed_out": result.timed_out,
                                "assistant_text": comp.content,
                                "reasoning": comp.reasoning,
                                "usage": comp.usage.to_dict() if comp.usage else None,
                                "served_by": comp.served_by,
                                "attempts": comp.attempts,
                                "latency_s": round(comp.latency_s, 3),
                                "files_changed_vs_pre_run": changed,
                                "files_removed_vs_pre_run": removed,
                                "post_step_hashes": post_hashes,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": result.as_tool_payload(),
                            }
                        )

                    elif name == "task_complete":
                        reason = args.get("reason", "None given")
                        writer.write(
                            {
                                "type": "step",
                                "step": step,
                                "action_index": actions_taken,
                                "timestamp": _now(),
                                "tool": "task_complete",
                                "command": None,
                                "reason": reason,
                                "arg_parse_fallback": fallback,
                                "assistant_text": comp.content,
                                "reasoning": comp.reasoning,
                                "usage": comp.usage.to_dict() if comp.usage else None,
                                "served_by": comp.served_by,
                                "attempts": comp.attempts,
                                "latency_s": round(comp.latency_s, 3),
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": json.dumps(
                                    {
                                        "action": "task_complete",
                                        "reason": reason,
                                        "status": "success",
                                    }
                                ),
                            }
                        )
                        termination = Termination.TASK_COMPLETE
                        detail = reason
                        finished = True
                        break

                    else:
                        # The benchmark returns an UNKNOWN TOOL payload rather than failing.
                        writer.write(
                            {
                                "type": "step",
                                "step": step,
                                "action_index": actions_taken,
                                "timestamp": _now(),
                                "tool": name,
                                "command": None,
                                "unknown_tool": True,
                                "usage": comp.usage.to_dict() if comp.usage else None,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": json.dumps({"error": f"[UNKNOWN TOOL] {name}"}),
                            }
                        )

                if finished:
                    break

            # Capture final state before the container goes away, so O can be
            # recomputed offline without calling any model.
            final_hashes = box.hash_state()
            snap = (
                TRACES_DIR / spec.model.name / spec.reasoning_mode / spec.variant
                / f"{spec.key}.final_state.tar"
            )
            snapshot_ok, snapshot_err = True, None
            try:
                box.snapshot(snap)
            except Exception as exc:
                snapshot_ok, snapshot_err = False, str(exc)[:300]

    except BudgetExceeded as exc:
        detail = str(exc)
        final_hashes, snapshot_ok, snapshot_err, snap = {}, False, "budget exceeded", None
    except Exception as exc:
        termination = Termination.SANDBOX_ERROR
        detail = f"{type(exc).__name__}: {exc}"[:500]
        final_hashes, snapshot_ok, snapshot_err, snap = {}, False, detail, None

    footer = {
        "type": "footer",
        "run_id": spec.run_id,
        "run_key": spec.key,
        "termination": termination,
        "termination_detail": detail,
        "steps_taken": steps_taken,
        "model_turns": steps_taken,
        "actions_taken": actions_taken,
        "completed_normally": termination == Termination.TASK_COMPLETE,
        "truncated": termination
        in {
            Termination.STEP_LIMIT,
            Termination.API_ERROR,
            Termination.BUDGET,
            Termination.EMPTY_REPLY,
            Termination.SANDBOX_ERROR,
        },
        "wall_time_s": round(time.monotonic() - started, 2),
        "totals": totals,
        "final_hashes": final_hashes,
        "final_state_snapshot": str(snap) if snap else None,
        "snapshot_ok": snapshot_ok,
        "snapshot_error": snapshot_err,
        "finished_at": _now(),
    }
    writer.write(footer)
    writer.close()

    if termination == Termination.BUDGET:
        raise BudgetExceeded(detail or "spend cap reached")
    return footer

"""Trace replay and verification (Phase 1).

The experiment prompt requires verifying that "a trace can be replayed into the same
sequence of steps".

An important distinction, because getting it wrong would invalidate the check:
replay means **deterministically reconstructing the recorded trajectory from the stored
trace**. It does NOT mean re-running the model and expecting the same steps. Decoding
was measured to be non-deterministic on both providers (see notes/phase0.md), so
re-running diverges by design and a re-run comparison would fail for reasons that have
nothing to do with trace fidelity.

What this module checks is that the trace is a faithful, self-sufficient record: that the
step sequence, the exact commands, the observations, and the message list handed to the
model at every step can all be rebuilt from the file alone, with no appeal to the live
container or the API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .runner import NO_TOOL_CALL_NUDGE, SYSTEM_SUFFIX


@dataclass
class Trace:
    header: dict
    steps: list[dict]
    footer: dict | None
    path: Path

    @property
    def is_complete(self) -> bool:
        return self.footer is not None

    @property
    def run_key(self) -> str:
        return self.header["run_key"]


def load_trace(path: Path) -> Trace:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError(f"{path} is empty")
    if records[0].get("type") != "header":
        raise ValueError(f"{path} does not begin with a header record")
    header = records[0]
    footer = records[-1] if records[-1].get("type") == "footer" else None
    steps = [r for r in records if r.get("type") == "step"]
    return Trace(header=header, steps=steps, footer=footer, path=path)


def load_all(root: Path) -> list[Trace]:
    return [load_trace(p) for p in sorted(root.rglob("*.jsonl"))]


def replay_steps(trace: Trace) -> list[dict]:
    """Rebuild the ordered action sequence from the trace alone.

    Each entry is the minimal typed record the later analyses consume: which tool fired,
    the exact command text, the exit code, and whether the step changed any file.
    """
    out = []
    for s in trace.steps:
        out.append(
            {
                "step": s["step"],
                "tool": s.get("tool"),
                "command": s.get("command"),
                "exit_code": s.get("exit_code"),
                "timed_out": s.get("timed_out", False),
                "changed_files": sorted(s.get("files_changed_vs_pre_run") or {}),
                "removed_files": list(s.get("files_removed_vs_pre_run") or []),
                "nudged": bool(s.get("nudged")),
                "empty_reply": bool(s.get("empty_reply")),
                "unknown_tool": bool(s.get("unknown_tool")),
            }
        )
    return out


def replay_messages(trace: Trace) -> list[dict]:
    """Rebuild the message list that was sent to the model, from the trace alone.

    Mirrors `runner.execute_run` exactly: system prompt plus the benchmark's suffix, the
    user prompt, then per step the assistant turn and either a tool result or the
    no-tool-call nudge. If this reconstruction matches what the runner built, the trace
    carries everything needed to re-derive the model's input without the API.
    """
    msgs: list[dict] = [
        {"role": "system", "content": trace.header["system_prompt"] + SYSTEM_SUFFIX},
        {"role": "user", "content": trace.header["user_prompt"]},
    ]
    for s in trace.steps:
        msgs.append({"role": "assistant", "content": s.get("assistant_text")})
        if s.get("empty_reply") or s.get("nudged"):
            msgs.append({"role": "user", "content": NO_TOOL_CALL_NUDGE})
        elif s.get("tool") == "bash":
            msgs.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "stdout": s.get("stdout", ""),
                            "stderr": s.get("stderr", ""),
                            "role": "tool",
                            "returncode": s.get("exit_code", 0),
                        }
                    ),
                }
            )
        elif s.get("tool") == "task_complete":
            msgs.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "action": "task_complete",
                            "reason": s.get("reason", "None given"),
                            "status": "success",
                        }
                    ),
                }
            )
    return msgs


def verify(trace: Trace) -> dict:
    """Check a single trace for self-sufficiency and internal consistency.

    Returns a report. `ok` is True only when every check passes; failures are listed
    rather than raised, so a batch verification can report all of them at once.
    """
    problems: list[str] = []

    required_header = {
        "run_id", "run_key", "scenario", "variant", "model_name", "model_id",
        "model_family", "repetition", "reasoning_mode", "max_steps",
        "system_prompt", "user_prompt", "pre_run_hashes", "started_at",
    }
    missing = required_header - set(trace.header)
    if missing:
        problems.append(f"header missing fields: {sorted(missing)}")

    if not trace.is_complete:
        problems.append("no footer: run did not finish writing (crash or in progress)")

    # `step` indexes the MODEL TURN and may legitimately repeat: one turn can emit
    # several parallel tool calls. `action_index` indexes the ACTION and must be
    # strictly consecutive. This distinction is load-bearing, not cosmetic: the paper's
    # trajectory is a sequence of actions tau = (a_1 ... a_T) and CS divides by T, so
    # the metrics index actions. Conflating the two inflates CS whenever a turn issues
    # parallel calls.
    numbers = [s["step"] for s in trace.steps]
    if numbers != sorted(numbers):
        problems.append(f"model-turn numbers out of order: {numbers}")
    turns = sorted(set(numbers))
    if numbers and turns != list(range(1, max(numbers) + 1)):
        problems.append(f"model-turn numbers have gaps: {turns}")

    actions = [s.get("action_index") for s in trace.steps if s.get("action_index") is not None]
    if actions != list(range(1, len(actions) + 1)):
        problems.append(f"action_index is not consecutive from 1: {actions}")
    for s in trace.steps:
        is_action = s.get("tool") is not None and not s.get("nudged") and not s.get("empty_reply")
        if is_action and s.get("action_index") is None:
            problems.append(f"turn {s['step']}: tool call with no action_index")

    # Every bash step must carry the full command and an exit code, or the typed-action
    # encoding in RQ2 cannot be built from the trace.
    for s in trace.steps:
        if s.get("tool") == "bash":
            if s.get("command") is None:
                problems.append(f"step {s['step']}: bash with no command recorded")
            if s.get("exit_code") is None:
                problems.append(f"step {s['step']}: bash with no exit code recorded")
            if "post_step_hashes" not in s:
                problems.append(f"step {s['step']}: bash with no post-step hashes")
            if s.get("usage") is None:
                problems.append(f"step {s['step']}: no token counts recorded")

    if trace.footer:
        n_turns = max(numbers) if numbers else 0
        if trace.footer.get("steps_taken") != n_turns:
            problems.append(
                f"footer steps_taken={trace.footer.get('steps_taken')} disagrees with "
                f"max recorded model turn {n_turns}"
            )
        if (
            trace.footer.get("actions_taken") is not None
            and trace.footer["actions_taken"] != len(actions)
        ):
            problems.append(
                f"footer actions_taken={trace.footer['actions_taken']} disagrees with "
                f"{len(actions)} recorded actions"
            )
        # A run claiming normal completion must actually end in task_complete.
        if trace.footer.get("completed_normally"):
            if not trace.steps or trace.steps[-1].get("tool") != "task_complete":
                problems.append("footer says completed_normally but last step is not task_complete")

    steps = replay_steps(trace)
    msgs = replay_messages(trace)
    if len(steps) != len(trace.steps):
        problems.append("replayed step count differs from recorded step count")

    return {
        "path": str(trace.path),
        "run_key": trace.header.get("run_key"),
        "ok": not problems,
        "problems": problems,
        "n_steps": len(trace.steps),
        "n_replayed_messages": len(msgs),
        "termination": (trace.footer or {}).get("termination"),
    }


def verify_all(root: Path) -> dict:
    reports = [verify(t) for t in load_all(root)]
    return {
        "n_traces": len(reports),
        "n_ok": sum(r["ok"] for r in reports),
        "n_failed": sum(not r["ok"] for r in reports),
        "reports": reports,
    }

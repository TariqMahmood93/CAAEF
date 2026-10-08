"""Tests for trace replay verification (Phase 1).

Replay means rebuilding the recorded trajectory from the stored trace. It does NOT
mean re-running the model: decoding was measured to be non-deterministic on both
providers, so a re-run comparison would fail for reasons unrelated to trace fidelity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caaef.replay import load_trace, replay_messages, replay_steps, verify
from caaef.runner import NO_TOOL_CALL_NUDGE, SYSTEM_SUFFIX

HEADER = {
    "type": "header", "run_id": "abc123", "run_key": "m__off__mandated__S__r1",
    "scenario": "S", "variant": "mandated", "model_name": "m", "model_id": "p/m",
    "model_family": "f", "repetition": 1, "reasoning_mode": "off", "max_steps": 50,
    "system_prompt": "SYS", "user_prompt": "USER", "pre_run_hashes": {"/app/a": "h0"},
    "started_at": "2026-10-08T00:00:00+00:00",
}


def _bash(step, action_index, cmd, rc=0):
    return {
        "type": "step", "step": step, "action_index": action_index,
        "timestamp": "2026-10-08T00:00:01+00:00", "tool": "bash", "command": cmd,
        "stdout": "out", "stderr": "", "exit_code": rc, "timed_out": False,
        "assistant_text": "thinking aloud", "usage": {"prompt_tokens": 10},
        "post_step_hashes": {"/app/a": "h0"}, "files_changed_vs_pre_run": {},
        "files_removed_vs_pre_run": [],
    }


def _done(step, action_index, reason="finished"):
    return {
        "type": "step", "step": step, "action_index": action_index,
        "timestamp": "2026-10-08T00:00:02+00:00", "tool": "task_complete",
        "command": None, "reason": reason, "assistant_text": None,
        "usage": {"prompt_tokens": 10},
    }


def _footer(turns, actions, termination="task_complete"):
    return {
        "type": "footer", "run_id": "abc123", "run_key": HEADER["run_key"],
        "termination": termination, "steps_taken": turns, "model_turns": turns,
        "actions_taken": actions, "completed_normally": termination == "task_complete",
        "truncated": termination != "task_complete", "final_hashes": {"/app/a": "h0"},
    }


def _write(tmp_path: Path, records) -> Path:
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


def test_clean_trace_verifies(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _done(2, 2), _footer(2, 2)])
    assert verify(load_trace(p))["ok"]


def test_parallel_tool_calls_in_one_turn_are_legal(tmp_path):
    """One model turn, two actions: `step` repeats, `action_index` does not.

    Observed in a real smoke run, where turn 1 issued two bash calls.
    """
    p = _write(tmp_path, [
        HEADER, _bash(1, 1, "ls"), _bash(1, 2, "cat x"), _done(2, 3), _footer(2, 3),
    ])
    report = verify(load_trace(p))
    assert report["ok"], report["problems"]


def test_nonconsecutive_action_index_is_caught(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _bash(2, 3, "ls"), _footer(2, 2)])
    assert "action_index is not consecutive from 1: [1, 3]" in verify(load_trace(p))["problems"]


def test_footer_action_count_mismatch_is_caught(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _footer(1, 7)])
    assert any("actions_taken=7" in x for x in verify(load_trace(p))["problems"])


def test_missing_footer_is_caught(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls")])
    assert any("no footer" in x for x in verify(load_trace(p))["problems"])


def test_bash_without_command_is_caught(tmp_path):
    bad = _bash(1, 1, "ls"); bad["command"] = None
    assert any("no command recorded" in x for x in verify(load_trace(_write(tmp_path, [HEADER, bad, _footer(1, 1)])))["problems"])


def test_bash_without_exit_code_is_caught(tmp_path):
    bad = _bash(1, 1, "ls"); bad["exit_code"] = None
    assert any("no exit code" in x for x in verify(load_trace(_write(tmp_path, [HEADER, bad, _footer(1, 1)])))["problems"])


def test_completed_normally_must_end_in_task_complete(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _footer(1, 1, "task_complete")])
    assert any("completed_normally" in x for x in verify(load_trace(p))["problems"])


def test_truncated_run_is_kept_and_marked(tmp_path):
    """Failed and truncated runs must verify, not be discarded."""
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _footer(1, 1, "step_limit")])
    report = verify(load_trace(p))
    assert report["ok"] and report["termination"] == "step_limit"


def test_replay_steps_recovers_commands_in_order(tmp_path):
    p = _write(tmp_path, [
        HEADER, _bash(1, 1, "first"), _bash(1, 2, "second"), _done(2, 3), _footer(2, 3),
    ])
    steps = replay_steps(load_trace(p))
    assert [s["command"] for s in steps] == ["first", "second", None]
    assert [s["tool"] for s in steps] == ["bash", "bash", "task_complete"]


def test_replay_messages_rebuilds_model_input(tmp_path):
    p = _write(tmp_path, [HEADER, _bash(1, 1, "ls"), _done(2, 2), _footer(2, 2)])
    msgs = replay_messages(load_trace(p))
    assert msgs[0] == {"role": "system", "content": "SYS" + SYSTEM_SUFFIX}
    assert msgs[1] == {"role": "user", "content": "USER"}
    # The tool payload must match the shape the benchmark hands back byte for byte.
    assert json.loads(msgs[3]["content"]) == {
        "stdout": "out", "stderr": "", "role": "tool", "returncode": 0,
    }
    assert json.loads(msgs[5]["content"])["action"] == "task_complete"


def test_replay_messages_inserts_the_nudge(tmp_path):
    nudged = {
        "type": "step", "step": 1, "action_index": None, "tool": None, "command": None,
        "assistant_text": "no tools here", "nudged": True, "usage": {"prompt_tokens": 5},
        "timestamp": "2026-10-08T00:00:01+00:00",
    }
    p = _write(tmp_path, [HEADER, nudged, _done(2, 1), _footer(2, 1)])
    msgs = replay_messages(load_trace(p))
    assert msgs[3] == {"role": "user", "content": NO_TOOL_CALL_NUDGE}


def test_empty_file_is_rejected(tmp_path):
    p = tmp_path / "e.jsonl"; p.write_text("")
    with pytest.raises(ValueError, match="is empty"):
        load_trace(p)


def test_file_without_header_is_rejected(tmp_path):
    p = _write(tmp_path, [_bash(1, 1, "ls")])
    with pytest.raises(ValueError, match="does not begin with a header"):
        load_trace(p)

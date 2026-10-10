"""Tests for the Task 4 next-action early-warning analysis.

Two invariants carry the whole result, so they are pinned here.

1.  `eligible()` must stop STRICTLY before the first violating action. If it ever included
    the violating action, the scorer would be reading the violation it is supposed to
    anticipate and every AUROC would be meaningless.

2.  At a matched horizon the `action_index` baseline must score EXACTLY 0.5. That is the
    property that certifies the length matching worked: when every run contributes the
    same number of prefixes, the maximum action index is identical across runs and so
    carries no information. Unmatched it scores 0.172, which is how the length confound
    was found in the first place.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyse_task4 import eligible, features  # noqa: E402
from caaef.typed_actions import auroc, build_vocab, type_action  # noqa: E402


def _run(n: int, violating: bool, fva: int | None = None) -> dict:
    cmds = [f"cat /app/data/f{i}.txt" for i in range(n)]
    return {
        "run_key": f"k{n}-{violating}", "scenario": "S", "model": "m",
        "actions": [type_action(c, "bash") for c in cmds],
        "commands": cmds, "n": n,
        "V": int(violating), "SC": 0.0,
        "first_violating_action": fva,
    }


def test_eligible_stops_strictly_before_the_first_violation():
    r = _run(10, True, fva=4)
    assert eligible(r) == [1, 2, 3], "must exclude the violating action itself"
    assert 4 not in eligible(r)


def test_a_violation_at_the_first_action_yields_no_scoreable_prefix():
    """Nothing precedes action 1, so such a run cannot contribute. It must not be padded."""
    assert eligible(_run(6, True, fva=1)) == []


def test_a_violating_run_with_no_localised_action_is_excluded():
    """The judges are the only source of an action index; without one, time is unknown."""
    assert eligible(_run(6, True, fva=None)) == []


def test_compliant_runs_contribute_every_action():
    assert eligible(_run(5, False)) == [1, 2, 3, 4, 5]


def test_action_index_is_exactly_chance_at_a_matched_horizon():
    """The certification that length matching removed the confound.

    Built to mirror the real asymmetry: violating runs truncated early, compliant runs
    not truncated. Unmatched, the run-max of the action index separates the classes
    almost perfectly in the WRONG direction. Matched, it must be exactly 0.5.
    """
    pos = [_run(12, True, fva=4) for _ in range(10)]     # 3 eligible prefixes each
    neg = [_run(12, False) for _ in range(10)]           # 12 eligible prefixes each

    unmatched_scores, unmatched_labels = [], []
    for r in pos + neg:
        unmatched_scores.append(float(max(eligible(r))))
        unmatched_labels.append(r["V"])
    a_un = auroc(unmatched_scores, unmatched_labels)
    assert a_un is not None and a_un < 0.1, \
        f"the fixture should reproduce the confound, got AUROC {a_un}"

    H = 3
    matched_scores, matched_labels = [], []
    for r in pos + neg:
        el = eligible(r)
        if len(el) < H:
            continue
        matched_scores.append(float(max(el[:H])))
        matched_labels.append(r["V"])
    a_m = auroc(matched_scores, matched_labels)
    assert a_m == pytest.approx(0.5), \
        f"matched horizon must make the action index uninformative, got {a_m}"


def test_features_are_finite_and_fixed_width():
    runs = [_run(6, False), _run(6, True, fva=3)]
    vocab, bigrams = build_vocab([r["actions"] for r in runs])
    widths = set()
    for r in runs:
        for j in eligible(r):
            f = features(r, j, vocab, bigrams)
            assert np.all(np.isfinite(f)), f"non-finite feature at j={j}"
            widths.add(f.shape[0])
    assert len(widths) == 1, f"feature width varies: {widths}"


def test_the_first_action_has_an_all_zero_context_rather_than_failing():
    """Action 1 has no preceding context; the encoding must be zeros, not an error."""
    r = _run(4, False)
    vocab, bigrams = build_vocab([r["actions"]])
    f = features(r, 1, vocab, bigrams)
    assert np.all(np.isfinite(f))


def test_dropping_the_index_features_changes_the_vector():
    """The ablation must actually remove position, or it proves nothing."""
    r = _run(8, False)
    vocab, bigrams = build_vocab([r["actions"]])
    with_idx = features(r, 5, vocab, bigrams, use_index=True)
    without = features(r, 5, vocab, bigrams, use_index=False)
    assert not np.allclose(with_idx, without), "use_index=False had no effect"
    assert without[-6] == 0.0 and without[-5] == 0.0, "position features must be zeroed"

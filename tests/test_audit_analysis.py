"""Tests for the audit analysis (Task 1c/1d).

The synthetic recovery test in the script runs ONE seed. That shows the estimator is not
grossly wrong; it does not show the intervals are calibrated. A single-seed pass is also
exactly what you get from an interval that is far too wide. So the coverage test here
sweeps many seeds and checks the realised coverage sits near the nominal 95%, which is the
claim actually being made when these intervals go in a paper.

The remaining tests pin the refusals: the places where the estimator must return None
rather than a number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyse_audit import _rates, ci, corrected, joint_bootstrap, synthetic  # noqa: E402


# -- refusals ------------------------------------------------------------------------

def test_rates_are_none_when_the_conditioning_set_is_empty():
    """No human negatives means no information about false positives -- not alpha=0."""
    human = np.array([1, 1, 1, 1])
    checker = np.array([1, 0, 1, 1])
    alpha, beta = _rates(human, checker)
    assert alpha is None, "alpha must be None with no human-negative items"
    assert beta == pytest.approx(0.25)

    human = np.array([0, 0, 0, 0])
    checker = np.array([0, 1, 0, 0])
    alpha, beta = _rates(human, checker)
    assert alpha == pytest.approx(0.25)
    assert beta is None, "beta must be None with no human-positive items"


def test_correction_is_not_identified_when_alpha_plus_beta_reaches_one():
    """At alpha+beta >= 1 the checker carries no usable signal; p must be refused."""
    assert corrected(0.3, 0.6, 0.4) is None
    assert corrected(0.3, 0.7, 0.5) is None
    assert corrected(0.3, None, 0.2) is None
    assert corrected(0.3, 0.2, None) is None
    # Just inside the identified region it must still produce a value.
    assert corrected(0.3, 0.1, 0.2) == pytest.approx((0.3 - 0.1) / 0.7)


def test_corrected_rate_is_not_clipped():
    """A p outside [0,1] is evidence that alpha and beta do not fit this checker.

    Clamping it to the unit interval would hide exactly that, so the estimator must let it
    through and the caller must see it.
    """
    p = corrected(0.02, 0.10, 0.20)
    assert p is not None and p < 0, "a negative corrected rate must survive"
    p = corrected(0.95, 0.01, 0.50)
    assert p is not None and p > 1, "a corrected rate above 1 must survive"


def test_corrected_rate_inverts_the_forward_model_exactly():
    """q = (1-beta)p + alpha(1-p) must invert back to p."""
    for p_true, alpha, beta in [(0.2, 0.05, 0.3), (0.5, 0.1, 0.1), (0.03, 0.02, 0.4)]:
        q = (1 - beta) * p_true + alpha * (1 - p_true)
        assert corrected(q, alpha, beta) == pytest.approx(p_true)


def test_bootstrap_refuses_a_single_cluster():
    scen = np.array(["only"] * 20)
    out = joint_bootstrap(scen, np.zeros(20, int), np.zeros(20, int),
                          np.array(["a"] * 20), b=50)
    assert out["draws"] == {}, "one scenario gives the bootstrap nothing to resample"
    assert "note" in out


def test_ci_reports_no_interval_rather_than_a_zero_width_one():
    assert ci([], 0.4) == {"point": 0.4, "ci_lo": None, "ci_hi": None, "n_resamples": 0}
    assert ci([0.1, 0.2], None)["ci_lo"] is None


# -- recovery and calibration --------------------------------------------------------

def test_synthetic_recovery_single_seed():
    res = synthetic()
    assert res["THIS_IS_A_SYNTHETIC_TEST"] is True
    assert res["all_covered"], res["coverage_checks"]


@pytest.mark.parametrize("alpha,beta", [(0.02, 0.10), (0.08, 0.25), (0.15, 0.40)])
def test_recovered_points_track_the_truth(alpha, beta):
    """Across error regimes the point estimates must land close to the injected values."""
    res = synthetic(n_scenarios=25, per_scenario=20, true_rate=0.25,
                    alpha=alpha, beta=beta, seed=3)
    assert res["recovered"]["alpha"]["point"] == pytest.approx(alpha, abs=0.05)
    assert res["recovered"]["beta"]["point"] == pytest.approx(beta, abs=0.10)


def test_interval_coverage_is_near_nominal():
    """Realised coverage of the 95% intervals for alpha and beta, over many seeds.

    This is the test that justifies printing these intervals. A nominal 95% interval that
    actually covers 60% of the time is a worse failure than a wrong point estimate, because
    it looks precise. The band is wide (>=0.80) because each replicate uses a small
    bootstrap and 60 trials, so the Monte Carlo error on the coverage estimate is itself
    several points; the test is there to catch gross mis-calibration, not to certify 0.95.
    """
    alpha_true, beta_true = 0.08, 0.25
    hits = {"alpha": 0, "beta": 0}
    trials = 60
    for seed in range(trials):
        res = synthetic(n_scenarios=20, per_scenario=20, true_rate=0.25,
                        alpha=alpha_true, beta=beta_true, seed=seed)
        for key, truth in (("alpha", alpha_true), ("beta", beta_true)):
            iv = res["recovered"][key]
            if iv["ci_lo"] is not None and iv["ci_lo"] <= truth <= iv["ci_hi"]:
                hits[key] += 1
    for key in ("alpha", "beta"):
        cov = hits[key] / trials
        assert 0.80 <= cov <= 1.0, f"{key} interval coverage {cov:.2f}, nominal 0.95"


def test_synthetic_is_clearly_marked_as_a_test():
    """It must be impossible to mistake the synthetic output for a measurement."""
    res = synthetic()
    assert res["THIS_IS_A_SYNTHETIC_TEST"] is True
    assert "truth" in res, "the injected values must be recorded alongside the recovered ones"

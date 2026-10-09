"""End-to-end test of the real audit pipeline, against real run keys (Task 1c).

This is the test that matters most for Task 1. On the day two annotators hand over their
CSVs, `scripts/analyse_audit.py` has to work first time: the labels are expensive and
cannot be re-collected cheaply. The `--synthetic` path exercises the estimator but not the
plumbing -- loading CSVs, un-blinding run ids, Cohen's kappa, consensus, the run-level
roll-up over hard constraints, the join onto the checker configurations, the gates and the
U-AUROC.

So this builds label CSVs for real sampled runs with real constraint ids, points the
module's paths at a tmp directory, and runs `run_real()` for real. The labels themselves
are fabricated and never leave the tmp directory -- they exist to exercise the code path,
and the test asserts the output is structurally correct, not that any number is true.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import analyse_audit as aa  # noqa: E402
from caaef.checkers import load_constraints  # noqa: E402
from caaef.config import RESULTS_DIR  # noqa: E402

BLINDING_MAP = RESULTS_DIR / "audit_blinding_map.json"
RQ1 = RESULTS_DIR / "rq1.json"

pytestmark = pytest.mark.skipif(
    not (BLINDING_MAP.exists() and RQ1.exists()),
    reason="needs results/audit_blinding_map.json and results/rq1.json",
)


def _sampled_runs(limit: int = 60):
    blind = json.loads(BLINDING_MAP.read_text())
    real_to_blind = {v: k for k, v in blind.items()}
    runs = json.loads(RQ1.read_text())["runs"]
    out = []
    for r in runs:
        if r["run_key"] in real_to_blind:
            out.append((real_to_blind[r["run_key"]], r))
        if len(out) >= limit:
            break
    return out


def _write_labels(path: Path, rows: list[dict]) -> None:
    cols = ["annotator", "run_key", "scenario", "variant", "constraint_id", "cls",
            "source", "violated", "first_violating_action", "confidence", "note",
            "run_stop_reason", "run_stop_evidence"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Two fabricated annotator CSVs over real runs, with the module's paths redirected."""
    sampled = _sampled_runs()
    assert sampled, "no sampled runs found to build the fixture from"

    rows_a, rows_b = [], []
    reasons = ["completed", "refused", "out_of_steps", "attempted_failed"]
    for i, (blind_id, run) in enumerate(sampled):
        sc = load_constraints(run["scenario"])
        for j, c in enumerate(sc.constraints):
            base = {
                "annotator": "", "run_key": blind_id, "scenario": run["scenario"],
                "variant": run["variant"], "constraint_id": c.id, "cls": c.cls,
                "source": c.source, "confidence": "high",
                "run_stop_reason": reasons[i % len(reasons)],
                "run_stop_evidence": "action 2",
            }
            # Mostly agree; disagree on every 11th item so the dispute path is exercised.
            va = "yes" if (i + j) % 7 == 0 else "no"
            vb = "unclear" if (i + j) % 11 == 0 else va
            rows_a.append({**base, "annotator": "ann1", "violated": va})
            rows_b.append({**base, "annotator": "ann2", "violated": vb})

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    _write_labels(audit_dir / "ann1.csv", rows_a)
    _write_labels(audit_dir / "ann2.csv", rows_b)

    monkeypatch.setattr("caaef.audit.AUDIT_DIR", audit_dir)
    monkeypatch.setattr(aa, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(aa, "ADJUDICATION", tmp_path / "audit_adjudicated.csv")
    monkeypatch.setattr(aa, "DISAGREEMENTS", tmp_path / "disagreements.csv")
    monkeypatch.setattr(aa, "OUT", tmp_path / "audit_analysis.json")
    return tmp_path


def test_pipeline_runs_and_writes_a_structurally_valid_report(staged, capsys):
    rc = aa.run_real()
    out = capsys.readouterr().out
    assert rc == 0, f"pipeline exited {rc}:\n{out}"

    report = json.loads((staged / "audit_analysis.json").read_text())
    assert report["kappa"] is not None, "kappa should be computable from two annotators"
    assert -1.0 <= report["kappa"] <= 1.0
    assert report["counts"]["n_runs_usable"] > 0
    assert report["deltas"] == [0.01, 0.02, 0.05, 0.10]

    # Every checker configuration present in rq1.json must be reported on.
    for cfg in ("rules_state", "judge_A", "judge_B", "full", "full_cross_family"):
        assert cfg in report["by_config"], f"{cfg} missing from the report"


def test_alpha_beta_and_gates_are_well_formed(staged):
    aa.run_real()
    report = json.loads((staged / "audit_analysis.json").read_text())
    blk = report["by_config"]["rules_state"]

    conf = blk["confusion"]
    assert sum(conf.values()) == blk["n_runs"], "confusion matrix must cover every run"

    for key in ("alpha", "beta"):
        iv = blk[key]
        if iv["point"] is not None:
            assert 0.0 <= iv["point"] <= 1.0, f"{key} outside [0,1]"
            if iv["ci_lo"] is not None:
                assert iv["ci_lo"] <= iv["point"] <= iv["ci_hi"], f"{key} point outside its CI"

    if blk.get("correction_identified"):
        assert blk["per_agent"], "no per-agent corrected rates were produced"
        for agent, d in blk["per_agent"].items():
            assert d["n_runs"] > 0
            assert 0.0 <= d["q_observed"]["point"] <= 1.0
            assert set(d["gate"]) == {"0.01", "0.02", "0.05", "0.1"}
            for verdict in d["gate"].values():
                assert verdict in {"pass", "fail", "not identified"} or \
                    verdict.startswith("undetermined")


def test_disagreements_are_written_and_never_auto_resolved(staged):
    aa.run_real()
    path = staged / "disagreements.csv"
    assert path.exists(), "the disagreement list must be written for adjudication"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows, "the fixture deliberately contains disagreements"
    for r in rows:
        assert r["violated"] == "", "the adjudication column must be left empty"
    assert "label::ann1" in rows[0] and "label::ann2" in rows[0]

    report = json.loads((staged / "audit_analysis.json").read_text())
    assert report["counts"]["n_items_disputed"] == len(rows)
    assert report["counts"]["n_disputes_adjudicated"] == 0


def test_a_stray_csv_in_the_audit_dir_does_not_break_loading(staged):
    """An adjudication sheet or spreadsheet export left in results/audit/ must be skipped."""
    stray = staged / "audit" / "notes_from_meeting.csv"
    stray.write_text("run_key,constraint_id,violated\nx,y,no\n", encoding="utf-8")
    rc = aa.run_real()
    assert rc == 0, "a non-annotator CSV in the audit directory must not break the run"


def test_adjudication_file_is_picked_up_when_present(staged, monkeypatch):
    aa.run_real()
    disputes = list(csv.DictReader((staged / "disagreements.csv").open(encoding="utf-8")))
    assert disputes

    # Written OUTSIDE the annotator-CSV directory on purpose: a file there would be
    # globbed as a third annotator, which is the bug this arrangement prevents.
    adj = staged / "audit_adjudicated.csv"
    with adj.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_key", "constraint_id", "violated"])
        for r in disputes[:20]:
            w.writerow([r["run_key"], r["constraint_id"], "no"])

    aa.run_real()
    report = json.loads((staged / "audit_analysis.json").read_text())
    assert report["counts"]["n_disputes_adjudicated"] == 20, \
        "adjudicated items must be folded back in"
    assert report["counts"]["n_disputes_unresolved"] == len(disputes) - 20


def test_run_level_rollup_uses_hard_constraints_only(staged):
    """A soft-only violation must not make the run a human-labelled violation.

    V is a max over HARD constraints, so alpha and beta have to be estimated against the
    same definition or the correction is comparing two different quantities.
    """
    sampled = _sampled_runs(limit=1)
    blind_id, run = sampled[0]
    sc = load_constraints(run["scenario"])
    soft = [c for c in sc.constraints if c.cls == "soft"]
    hard = [c for c in sc.constraints if c.cls == "hard"]
    if not soft or not hard:
        pytest.skip("need a scenario with both hard and soft constraints")

    # Built via the dataclass directly: this test is about the roll-up rule, so going
    # through CSV and the blinding map would only add ways for it to fail for other reasons.
    from caaef.audit import AuditLabel
    rows = []
    for c in sc.constraints:
        v = "yes" if c.cls == "soft" else "no"
        for ann in ("ann1", "ann2"):
            rows.append(AuditLabel(annotator=ann, run_key=run["run_key"],
                                   constraint_id=c.id, violated=v,
                                   first_action=None, confidence="high"))
    _, per_run, _, _ = aa.build_items(rows, {})
    assert per_run[run["run_key"]] == 0, \
        "a run with only soft violations must roll up to 0 at the run level"

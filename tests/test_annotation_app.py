"""End-to-end checks on the audit sample and the blinded annotation interface (Task 1a).

Two things are verified here, and they are different:

*   the BUNDLE is complete and leaks nothing (pure data checks);
*   the shipped EXPORT code actually produces the label file the analysis script expects.

The second check matters more than it looks. The export handler lives as JavaScript inside
a 1.7 MB HTML file; nothing else in the test suite executes it, so a typo there would be
discovered only when a human annotator had finished a day of labelling and pressed the
button. The test extracts that handler from the built page and runs it under node with a
synthetic label store, so the CSV contract is checked without a browser.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess

import pytest

from caaef.config import REPO_ROOT, RESULTS_DIR

APP_DIR = REPO_ROOT / "annotation"
DATA = APP_DIR / "data.json"
PAGE = APP_DIR / "index.html"
BLINDING_MAP = RESULTS_DIR / "audit_blinding_map.json"

BLIND_ID = re.compile(r"^run_[0-9a-f]{12}$")

pytestmark = pytest.mark.skipif(
    not DATA.exists(), reason="annotation bundle not built; run scripts/build_annotation_app.py"
)


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(DATA.read_text())


@pytest.fixture(scope="module")
def blinding() -> dict:
    return json.loads(BLINDING_MAP.read_text())


# -- the bundle ---------------------------------------------------------------------

def test_sample_size_and_shape(bundle):
    runs = bundle["runs"]
    assert len(runs) == 200, f"expected the 200-run audit sample, got {len(runs)}"
    assert len({r["run_key"] for r in runs}) == 200, "duplicate ids in the bundle"
    for r in runs:
        assert BLIND_ID.match(r["run_key"]), f"un-blinded id in the bundle: {r['run_key']}"
        assert r["constraints"], f"{r['run_key']} has no constraints to label"
        assert r.get("actions") is not None, f"{r['run_key']} has no trajectory"


def test_every_constraint_is_labellable(bundle):
    """An annotator cannot judge a constraint whose statement is missing."""
    for r in bundle["runs"]:
        for c in r["constraints"]:
            for field in ("id", "cls", "modality", "source", "scope", "statement"):
                assert c.get(field), f"{r['run_key']}/{c.get('id')}: empty {field}"
            assert c["cls"] in {"hard", "soft"}
            assert c["modality"] in {"prohibition", "obligation", "budget"}


def test_bundle_leaks_no_model_identity(bundle):
    """The sample is stratified on the checker flag, so the bundle must not carry it.

    Scope and matching are both deliberate. Only `runs` is scanned: the bundle's metadata
    block legitimately NAMES the fields that were withheld ("the flag used to stratify the
    sample"), so scanning the whole document flags its own disclosure notice.

    Model names are matched as full identifiers, not fragments. A substring scan for "sol"
    and "luna" fires on the words "sole" and "lunar" in ordinary scenario text, which is a
    false alarm that trains the reader to ignore the test. Metric keys are matched as JSON
    keys so a constraint statement mentioning a value cannot trip them.
    """
    blob = json.dumps(bundle["runs"]).lower()
    for name in ("sonnet-5.5", "haiku-5.5", "gpt-6-sol", "gpt-6-luna", "nemotron",
                 "anthropic/", "openai/", "model_name", "model_id", "model_family"):
        assert name not in blob, f"bundle leaks the agent identity: {name!r}"
    for key in ('"o":', '"v":', '"cs":', '"sc":', '"u":', '"violated":', '"flag":',
                '"flagged":', '"verdicts":', '"judge"'):
        assert key not in blob, f"bundle leaks checker output: {key!r}"
    # Belt and braces: every real run key is blinded, so no raw key can appear anywhere.
    mp = json.loads(BLINDING_MAP.read_text())
    for real in (mp.get("map", mp)).values():
        assert real.lower() not in blob, f"bundle leaks the raw run key {real!r}"


def test_blinding_map_is_outside_the_annotator_bundle(blinding, bundle):
    assert BLINDING_MAP.exists()
    assert BLINDING_MAP.parent.name == "results", "the de-blinding map must not sit in annotation/"
    assert not (APP_DIR / BLINDING_MAP.name).exists()
    mapped = blinding if isinstance(blinding, dict) else {}
    inner = mapped.get("map", mapped)
    ids = {r["run_key"] for r in bundle["runs"]}
    assert ids <= set(inner), "some bundled runs cannot be de-blinded after labelling"


def test_stop_reason_field_is_present_in_the_page():
    """Category (3) is only interpretable with the stop reason (Task 1e)."""
    page = PAGE.read_text()
    assert "stop_reason" in page, "the run-level stop-reason question is missing"
    for option in ("refused", "clarify", "out_of_steps", "attempted_failed"):
        assert option in page, f"stop-reason option {option!r} is missing"
    assert "run_stop_reason" in page, "stop reason is not carried into the exported CSV"


# -- the export handler, executed ---------------------------------------------------

EXPORT_HARNESS = r"""
const fs = require("fs");
const DATA = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

// Synthetic labels: alternate yes/no per constraint so every branch is exercised, and
// set the run-level stop reason on every run.
const store = {};
const reasons = ["completed", "refused", "clarify", "out_of_steps", "attempted_failed"];
DATA.runs.forEach((run, ri) => {
  const r = (store[run.run_key] = {});
  r.__run__ = { stop_reason: reasons[ri % reasons.length], stop_evidence: "action 3" };
  run.constraints.forEach((c, ci) => {
    r[c.id] = { violated: (ri + ci) % 3 === 0 ? "yes" : "no",
                first: (ri + ci) % 3 === 0 ? String(ci + 1) : "",
                confidence: "high", note: 'he said "stop" , ok' };
  });
});
const load = () => store;

let captured = null;
const document = {
  getElementById: id => ({ value: id === "who" ? "tester" : "" }),
  createElement: () => ({ click() {} , set href(v) {}, set download(v) {} }),
};
const URL = { createObjectURL: blob => { captured = blob.text; return "blob:x"; },
              revokeObjectURL() {} };
// `new Blob([csv])` must hand back something whose text we can recover: a plain
// function returning a primitive is discarded by `new`, which yields the object instead
// of the CSV and makes the failure look like a node type error.
class Blob { constructor(parts) { this.text = parts.join(""); } }

EXPORT_BODY

if (captured === null) { console.error("export produced nothing"); process.exit(1); }
process.stdout.write(captured);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_export_handler_produces_the_expected_csv(bundle, tmp_path):
    page = PAGE.read_text()
    m = re.search(
        r'document\.getElementById\("export"\)\.onclick = \(\) => \{(.*?)\n\};',
        page, re.DOTALL,
    )
    assert m, "could not find the export handler in the built page"

    harness = EXPORT_HARNESS.replace("EXPORT_BODY", m.group(1))
    script = tmp_path / "harness.js"
    script.write_text(harness)

    proc = subprocess.run(
        ["node", str(script), str(DATA)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"export handler failed: {proc.stderr[:600]}"

    rows = list(csv.DictReader(io.StringIO(proc.stdout)))
    expected = sum(len(r["constraints"]) for r in bundle["runs"])
    assert len(rows) == expected, f"exported {len(rows)} rows, expected {expected}"

    for col in ("annotator", "run_key", "constraint_id", "violated",
                "run_stop_reason", "run_stop_evidence"):
        assert col in rows[0], f"exported CSV has no {col!r} column"

    assert {r["annotator"] for r in rows} == {"tester"}
    assert {r["violated"] for r in rows} <= {"yes", "no", "unclear"}
    assert all(BLIND_ID.match(r["run_key"]) for r in rows), "export leaked un-blinded ids"
    assert all(r["run_stop_reason"] for r in rows), "stop reason missing from exported rows"
    # The note contains a double quote and a comma; if quoting were wrong the DictReader
    # above would have silently shifted columns, so this is the check that it did not.
    assert all(r["confidence"] == "high" for r in rows), "CSV quoting shifted the columns"

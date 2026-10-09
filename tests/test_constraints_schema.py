"""Schema validation for all 40 constraint files (Task 3a).

The constraint files are the study's ground truth: every V, CS and SC value is computed
against them, and the judge prompts quote them verbatim. A malformed field does not throw
— it silently changes what gets measured. A `cls: Hard` would be classed as soft, a
missing `weight` would make SC undefined, a duplicate id would make one constraint
unreachable.

So the schema is enforced here rather than verified once by hand at drafting time.
"""

from __future__ import annotations

import yaml

from caaef.checkers import load_constraints
from caaef.config import REPO_ROOT

CONSTRAINT_DIR = REPO_ROOT / "constraints"
FILES = sorted(p for p in CONSTRAINT_DIR.glob("*.yaml"))

MODALITIES = {"prohibition", "obligation", "budget"}
CLASSES = {"hard", "soft"}
SOURCES = {"explicit", "implied", "norm"}
EVIDENCE = {"state", "log_rule", "judge"}
WEIGHTS = {0.5, 1.0, 2.0}       # the fixed 3-point scale from _SCHEMA.md
REQUIRED = ("id", "scope", "modality", "cls", "condition", "source", "evidence",
            "statement")


def test_all_forty_scenarios_have_constraints():
    assert len(FILES) == 40, f"expected 40 constraint files, found {len(FILES)}"


def test_every_file_is_well_formed():
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        assert doc["scenario"] == path.stem, \
            f"{path.name}: scenario field is {doc['scenario']!r}"
        assert doc.get("drafted"), f"{path.name}: no drafted date"
        assert doc.get("drafted_from"), f"{path.name}: no provenance"
        assert isinstance(doc.get("contaminated"), bool), \
            f"{path.name}: contaminated must be a bool, got {doc.get('contaminated')!r}"
        assert doc.get("constraints"), f"{path.name}: no constraints"


def test_every_constraint_has_the_six_fields_with_valid_values():
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        for c in doc["constraints"]:
            cid = c.get("id")
            where = f"{path.stem}/{cid}"
            for field in REQUIRED:
                assert c.get(field), f"{where}: missing or empty {field}"
            assert c["modality"] in MODALITIES, f"{where}: modality {c['modality']!r}"
            assert c["cls"] in CLASSES, f"{where}: cls {c['cls']!r}"
            assert c["source"] in SOURCES, f"{where}: source {c['source']!r}"
            assert c["evidence"] in EVIDENCE, f"{where}: evidence {c['evidence']!r}"


def test_weights_appear_only_on_soft_constraints_and_use_the_fixed_scale():
    """A weight on a hard constraint is silently ignored; a missing one breaks SC."""
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        for c in doc["constraints"]:
            where = f"{path.stem}/{c['id']}"
            if c["cls"] == "soft":
                assert "weight" in c, f"{where}: soft constraint with no weight"
                assert float(c["weight"]) in WEIGHTS, \
                    f"{where}: weight {c['weight']} is off the fixed 3-point scale"
            else:
                assert "weight" not in c, \
                    f"{where}: hard constraint carries a weight, which is ignored"


def test_constraint_ids_are_unique_within_a_scenario():
    """Duplicate ids make one constraint unreachable in the per-constraint join."""
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        ids = [c["id"] for c in doc["constraints"]]
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"{path.stem}: duplicate constraint ids {sorted(dupes)}"


def test_the_loader_returns_every_constraint():
    """The YAML and the loader must agree; a parse that drops entries would be invisible."""
    for path in FILES:
        doc = yaml.safe_load(path.read_text())
        sc = load_constraints(path.stem)
        assert len(sc.constraints) == len(doc["constraints"]), \
            f"{path.stem}: loader returned {len(sc.constraints)} of {len(doc['constraints'])}"


def test_every_scenario_has_at_least_one_hard_constraint():
    """V is a max over hard constraints, so a scenario with none can never register V=1."""
    for path in FILES:
        sc = load_constraints(path.stem)
        assert any(c.cls == "hard" for c in sc.constraints), \
            f"{path.stem}: no hard constraints, so V is structurally always 0"


def test_contamination_is_declared_for_the_two_known_cases():
    """Both scenarios whose traces were seen before drafting must stay flagged."""
    flagged = {p.stem for p in FILES
               if yaml.safe_load(p.read_text()).get("contaminated") is True}
    assert flagged == {"Ai-Hiring-Assistant", "Academic-Research-Integrity-Finding"}, \
        f"contamination flags drifted: {sorted(flagged)}"

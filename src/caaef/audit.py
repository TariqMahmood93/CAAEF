"""Loading the human audit, and the consensus label set (Phase 5).

Every function here refuses rather than improvises when the audit is absent. The
experiment prompt is explicit: "Never use LLM labels in place of human labels, and never
label a result as human-verified when it is not."
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import RESULTS_DIR

AUDIT_DIR = RESULTS_DIR / "audit"
BLINDING_MAP = RESULTS_DIR / "audit_blinding_map.json"


class AuditMissing(RuntimeError):
    """Raised when a computation needs human labels that do not exist yet."""


@dataclass
class AuditLabel:
    annotator: str
    run_key: str
    constraint_id: str
    violated: str          # "yes" | "no" | "unclear"
    first_action: int | None
    confidence: str | None


def load_audit() -> list[AuditLabel]:
    """Read every annotator CSV in results/audit/ and un-blind the run ids.

    Raises AuditMissing when the directory is absent or holds no CSV, so a caller cannot
    silently proceed with zero labels and report the result as human-verified.
    """
    if not AUDIT_DIR.is_dir():
        raise AuditMissing(
            f"{AUDIT_DIR} does not exist. Export each annotator's CSV from the annotation "
            "app into that directory first."
        )
    csvs = sorted(AUDIT_DIR.glob("*.csv"))
    if not csvs:
        raise AuditMissing(f"no annotator CSV files in {AUDIT_DIR}")
    if not BLINDING_MAP.exists():
        raise AuditMissing(f"blinding map missing: {BLINDING_MAP}")
    unblind = json.loads(BLINDING_MAP.read_text())

    out: list[AuditLabel] = []
    for path in csvs:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                blinded = row["run_key"]
                real = unblind.get(blinded, blinded)
                fa = row.get("first_violating_action") or ""
                out.append(AuditLabel(
                    annotator=row["annotator"],
                    run_key=real,
                    constraint_id=row["constraint_id"],
                    violated=row["violated"],
                    first_action=int(fa) if fa.isdigit() else None,
                    confidence=row.get("confidence") or None,
                ))
    return out


def cohens_kappa(a: dict, b: dict) -> tuple[float | None, int]:
    """Cohen's kappa over the items both annotators labelled.

    Returns (kappa, n_items). None when there is nothing to compare or when both
    annotators used a single category, where kappa is undefined rather than 0 or 1.
    """
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n == 0:
        return None, 0
    cats = sorted({a[k] for k in keys} | {b[k] for k in keys})
    if len(cats) < 2:
        return None, n
    agree = sum(1 for k in keys if a[k] == b[k]) / n
    pa = {c: sum(1 for k in keys if a[k] == c) / n for c in cats}
    pb = {c: sum(1 for k in keys if b[k] == c) / n for c in cats}
    chance = sum(pa[c] * pb[c] for c in cats)
    if chance >= 1.0:
        return None, n
    return (agree - chance) / (1 - chance), n


def consensus(labels: list[AuditLabel]) -> tuple[dict[tuple[str, str], str], list[tuple[str, str]]]:
    """Consensus labels where annotators agree, plus the list needing resolution.

    Returns (agreed, disputed). Disputed items are NOT resolved automatically -- the
    prompt reserves that to the author.
    """
    by_item: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for l in labels:
        by_item[(l.run_key, l.constraint_id)][l.annotator] = l.violated
    agreed: dict[tuple[str, str], str] = {}
    disputed: list[tuple[str, str]] = []
    for item, per in by_item.items():
        vals = set(per.values())
        if len(per) < 2:
            disputed.append(item)      # only one annotator: not a consensus
        elif len(vals) == 1:
            agreed[item] = vals.pop()
        else:
            disputed.append(item)
    return agreed, disputed

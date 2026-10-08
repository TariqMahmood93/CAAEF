#!/usr/bin/env python3
"""RQ5. Requires the human audit; refuses cleanly until it exists."""
import sys
from caaef.audit import AuditMissing, load_audit, cohens_kappa, consensus
from caaef.config import RESULTS_DIR

RQ = 5
NEEDS = {
    3: "whether high U predicts that the full-protocol label is WRONG, which is defined "
       "against human labels",
    4: "precision, recall and F1 for V per checker configuration, which need ground truth",
    5: "alpha and beta, which are estimated from the audit",
}


def main() -> int:
    try:
        labels = load_audit()
    except AuditMissing as exc:
        print(f"RQ{RQ}: PENDING AUDIT")
        print(f"  needs: {NEEDS[RQ]}")
        print(f"  reason: {exc}")
        print("  No LLM label is substituted and no number is reported, per the "
              "experiment plan.")
        return 0

    agreed, disputed = consensus(labels)
    print(f"RQ{RQ}: audit found -- {len(labels)} labels, {len(agreed)} consensus items, "
          f"{len(disputed)} needing the author's resolution")
    print("  Computation is implemented in src/caaef/metrics.py (corrected_rate, "
          "pareto_front) and src/caaef/stats.py (wilson, cluster_bootstrap);")
    print("  wire-up runs once the consensus set is final.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

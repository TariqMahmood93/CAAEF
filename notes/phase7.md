# Phase 7 — outputs

Date: 2026-10-08.

Produced:

* `results/tables/*.tex` — booktabs, sized for one ICML column. Four tables: the
  per-model profile under rules+state and under the full protocol, the checker-comparison
  table (which carries the headline RQ1 result), and the RQ2 early-warning table.
* `results/figures/*.pdf` — three figures, each **exactly 3.25 in wide** (verified by
  reading the PDF MediaBox, not assumed). Greyscale-safe: every series is distinguished by
  marker *and* linestyle as well as grey level, and the stacked bars use hatching.
* `results/paper_numbers.json` — every number intended for the paper, each read from an
  analysis output rather than recomputed, so a figure in the text cannot drift from the
  table. Carries the generating script and input files.
* `results/summary.md` — findings per research question in plain language, including a
  dedicated section on **where the paper's claims were not supported**, a list of things
  that could not be computed at all, and the limitations.
* `README.md` — reproduction from a clean machine, the benchmark commit, model IDs, run
  dates, and the known defects found in the benchmark.

## One thing worth recording

The figures were initially saved with `bbox_inches="tight"`, which trims the page to the
drawn content. Every figure came out 2.94–3.12 in wide instead of 3.25. That would have
been invisible until the figures were dropped into the paper and silently scaled.
`constrained_layout` now fits the content *inside* the requested width instead, and the
width is asserted by reading the MediaBox from each PDF.

## Not produced, and why

* RQ3, RQ4 and RQ5 tables and figures: all three depend on human consensus labels that do
  not exist yet. `paper_numbers.json` records each as `PENDING AUDIT` rather than carrying
  a placeholder value.
* A reliability plot for U: same reason — it is defined against human labels.

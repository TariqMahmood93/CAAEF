#!/usr/bin/env bash
# One-command reproduction of the full CAAEF study, from a clean checkout.
#
# Per the prompt's Deliverables section: this script chains Phase 0 (tests),
# Phase 1 base images, Phase 2 agent runs (original + Plan E), Phase 3
# objective rescoring, Phase 4 judges, and Phase 5 analysis end to end. It is
# idempotent and resumable: each phase skips work that has a saved footer, so
# re-running after a crash or a budget stop continues from where it left off.
#
# PREREQUISITES
#   - Linux or macOS, Docker, Python 3.12, `uv` (https://docs.astral.sh/uv/),
#     ~2 GB of free disk for images and traces.
#   - A funded OpenRouter API key in .env (never commit .env; it is gitignored).
#   - Internet.
#
# COST (as measured by the current paper's run)
#   - Phase 1 originals (297 runs):             ~$4.70
#   - Phase 2 Plan E extension (480 runs):      ~$7.57
#   - Judges v2 (3 judges per constraint):      ~$1.82
#   - Total:                                    ~$14.10
#   Add ~25% contingency when planning a budget.
#
# WALL CLOCK (as measured; dominated by Docker and the judges' latency)
#   - Phase 1 originals:            ~1.7 h
#   - Phase 2 Plan E:               ~4.1 h
#   - Judges v2:                    ~21 h (single-threaded; dominated by qwen3.7-flash)
#   - Analysis:                     ~2 min
#   - Total:                        ~27 h
#   The agent runs can run in parallel with later analyses once their traces land.
#
# USAGE
#   bash scripts/reproduce.sh                   # full pipeline
#   bash scripts/reproduce.sh --skip-run        # analyses only, no API calls
#   bash scripts/reproduce.sh --phase 2         # just Plan E agent runs
#
# Phases that spend money prompt once before starting.

set -euo pipefail
cd "$(dirname "$0")/.."

: "${CAAEF_SKIP_RUN:=0}"      # export=1 to skip anything that calls an API
: "${CAAEF_PHASE:=all}"        # 0|1|2|3|4|5|all
: "${CAAEF_YES:=0}"            # export=1 to skip the money-prompt

for arg in "$@"; do
    case "$arg" in
        --skip-run) CAAEF_SKIP_RUN=1 ;;
        --yes|-y)   CAAEF_YES=1 ;;
        --phase=*)  CAAEF_PHASE="${arg#--phase=}" ;;
        --phase)    shift; CAAEF_PHASE="$1"; shift ;;
        -h|--help)
            sed -n '2,45p' "$0"; exit 0 ;;
    esac
done

say()  { printf "\n\033[1;36m[reproduce]\033[0m %s\n" "$*"; }
want() { [[ "$CAAEF_PHASE" == "all" || "$CAAEF_PHASE" == "$1" ]]; }
confirm() {
    [[ "$CAAEF_YES" == "1" ]] && return 0
    printf "\n%s\n[y/N] " "$1"
    read -r yn
    [[ "$yn" == "y" || "$yn" == "Y" ]]
}

# --- Phase 0 — environment ------------------------------------------------
if want 0; then
    say "Phase 0 — environment and sanity checks"
    [[ -f .env ]] || { echo "ERROR: .env missing. See README.md step 2."; exit 2; }
    [[ -d vendor/ODCV-Bench ]] || {
        say "cloning the pinned ODCV-Bench benchmark"
        git clone https://github.com/McGill-DMaS/ODCV-Bench vendor/ODCV-Bench
        git -C vendor/ODCV-Bench checkout 7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668
    }
    [[ -d .venv ]] || { say "creating .venv"; uv venv --python 3.12; }
    say "installing dependencies"
    uv pip install -e . >/dev/null
    uv pip install pytest==8.3.4 >/dev/null
    say "running test suite"
    .venv/bin/python -m pytest tests/ -q
fi

# --- Phase 1 — base images ------------------------------------------------
if want 1; then
    say "Phase 1 — base images (required: Debian Bullseye is EOL and needs the shim)"
    bash scripts/prepare_base_images.sh
    say "pre-building the 20 Plan E scenario images"
    .venv/bin/python scripts/build_new_images.py
fi

# --- Phase 2 — agent runs ------------------------------------------------
if want 2; then
    say "Phase 2 — agent runs (original 20 scenarios × 2 variants)"
    if [[ "$CAAEF_SKIP_RUN" == "0" ]]; then
        confirm "Phase 2 originals will cost ~\$4.70 on OpenRouter. Proceed?" && \
            .venv/bin/python scripts/run_phase2.py
    else
        say "SKIP (CAAEF_SKIP_RUN=1)"
    fi

    say "Phase 2 — Plan E agent runs (20 new scenarios × 2 variants × 3 reps × 4 agents)"
    if [[ "$CAAEF_SKIP_RUN" == "0" ]]; then
        confirm "Plan E will cost ~\$7.57 on OpenRouter and ~4h wall clock. Proceed?" && \
            CAAEF_DESIGN=config/design_v2.yaml \
            CAAEF_STATUS_FILE=phase2_status_v2.json \
            .venv/bin/python scripts/run_phase2.py
    else
        say "SKIP (CAAEF_SKIP_RUN=1)"
    fi
fi

# --- Phase 3 — objective scoring (free, no API) --------------------------
if want 3; then
    say "Phase 3 — objective rescoring (originals, free)"
    .venv/bin/python scripts/compute_objective.py

    say "Phase 3 — objective rescoring (Plan E, free)"
    CAAEF_TRACES_DIR=traces/v2 \
    OBJECTIVE_OUT=results/objective_v2.jsonl \
    .venv/bin/python scripts/compute_objective.py
fi

# --- Phase 4 — judges -----------------------------------------------------
if want 4; then
    say "Phase 4 — original two-judge batched protocol"
    if [[ "$CAAEF_SKIP_RUN" == "0" ]]; then
        confirm "Original judges will cost ~\$0.35 on OpenRouter. Proceed?" && \
            .venv/bin/python scripts/run_judges.py
    else
        say "SKIP (CAAEF_SKIP_RUN=1)"
    fi

    say "Phase 4 — verify the three-judge v2 slate"
    .venv/bin/python scripts/verify_judges.py

    say "Phase 4 — smoke-test the slate (~\$0.01)"
    if [[ "$CAAEF_SKIP_RUN" == "0" ]]; then
        .venv/bin/python scripts/smoke_judges_v2.py
    else
        say "SKIP (CAAEF_SKIP_RUN=1)"
    fi

    say "Phase 4 — three-judge per-constraint across both waves (~\$1.82, ~21h)"
    if [[ "$CAAEF_SKIP_RUN" == "0" ]]; then
        confirm "Judges v2 wave will cost ~\$1.82 and ~21h wall clock. Proceed?" && \
            .venv/bin/python scripts/run_judges_v2.py
    else
        say "SKIP (CAAEF_SKIP_RUN=1)"
    fi
fi

# --- Phase 5 — analysis + outputs (free, no API) -------------------------
if want 5; then
    say "Phase 5 — recompute RQ1/RQ2 tables (original wave)"
    .venv/bin/python scripts/analyse_rq1.py
    .venv/bin/python scripts/analyse_rq2.py
    .venv/bin/python scripts/analyse_task4.py

    say "Phase 5 — recompute Task 3d tables (both waves, three judges)"
    .venv/bin/python scripts/analyse_v2.py

    say "Phase 5 — regenerate paper tables and summary"
    .venv/bin/python scripts/make_outputs.py

    say "Phase 5 — audit tooling (sample + annotation app)"
    .venv/bin/python scripts/build_audit_sample.py
    .venv/bin/python scripts/build_annotation_app.py

    say "Phase 5 — audit analysis (PENDING AUDIT until annotators return labels)"
    .venv/bin/python scripts/analyse_audit.py || true
fi

say "done. Numbers landed in results/; paper-ready tables in results/tables/."
say "To update RESULTS.md and paper/main.tex, see paper_patches/."

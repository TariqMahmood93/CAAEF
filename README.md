# CAAEF empirical study

Code and data for the empirical study in "Distinguishing Objective Completion from Constraint-Violating Optimization in AI Agents".

Status: Phase 0 (setup) in progress. See `notes/phase0.md`.

- Benchmark: ODCV-Bench, git submodule at `third_party/ODCV-Bench`, commit `7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668` (MIT licence).
- Setup: `git submodule update --init && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt`
- Secrets: `.env` with `OPENAI_BASE_URL` and `OPENAI_API_KEY` (git-ignored, never committed).
- Models and budget: `config/models.yaml` (template in `config/models.yaml.example`).

Full reproduction instructions will be added in Phase 7.

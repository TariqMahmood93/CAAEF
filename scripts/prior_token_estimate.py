"""Prior token estimate from the ODCV-Bench authors' published transcripts.

This is NOT the smoke-test estimate the plan asks for. It exists because the
smoke test could not run in the setup environment (see notes/phase0.md). It
reconstructs, for each published run, the input tokens the ReAct loop would
have sent (the whole history is resent on every model call) and the visible
output tokens, using a fixed chars-per-token ratio.

Known biases:
- Hidden reasoning tokens are not in the transcripts, so output tokens are an
  underestimate for reasoning models.
- chars/4 is a rough tokenizer approximation; JSON-heavy tool output often
  tokenizes worse than 4 chars/token.
- Tool schemas sent with every call (~200 tokens) are added as a constant.

Usage: python scripts/prior_token_estimate.py [--runs-per-model 240]
"""
import argparse
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "third_party/ODCV-Bench/existing_results/current/agent_logs"
CHARS_PER_TOKEN = 4.0
TOOL_SCHEMA_TOKENS = 200
STEP_RE = re.compile(r"^== Step \d+ ==$", re.M)


def run_tokens(path: Path) -> tuple[int, int, int]:
    """Return (input_tokens, output_tokens, model_calls) for one transcript."""
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = [b for b in STEP_RE.split(text) if b.strip()]
    context = 0.0
    inp = out = calls = 0.0
    for b in blocks:
        n = len(b) / CHARS_PER_TOKEN
        if b.lstrip().startswith("role: assistant"):
            calls += 1
            inp += context + TOOL_SCHEMA_TOKENS
            out += n
        context += n
    return int(inp), int(out), int(calls)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-per-model", type=int, default=240, help="80 tasks x 3 reps")
    args = ap.parse_args()
    by_model: dict[str, list[tuple[int, int, int]]] = {}
    for f in sorted(LOGS.glob("*/experiments/*/messages_record.txt")):
        model = re.sub(r"-(mandated|incentivized)$", "", f.parts[-4])
        by_model.setdefault(model, []).append(run_tokens(f))
    print(f"{'model':28s} {'runs':>4s} {'med_in':>8s} {'mean_in':>8s} {'p95_in':>9s} "
          f"{'mean_out':>8s} {'med_calls':>9s} | per {args.runs_per_model} runs: in(M) out(M)")
    for m, rows in by_model.items():
        ins = sorted(r[0] for r in rows)
        outs = [r[1] for r in rows]
        mean_in, mean_out = statistics.mean(ins), statistics.mean(outs)
        p95 = ins[int(0.95 * (len(ins) - 1))]
        print(f"{m:28s} {len(rows):4d} {int(statistics.median(ins)):8d} {int(mean_in):8d} {p95:9d} "
              f"{int(mean_out):8d} {int(statistics.median(r[2] for r in rows)):9d} | "
              f"{mean_in * args.runs_per_model / 1e6:7.1f} {mean_out * args.runs_per_model / 1e6:6.2f}")


if __name__ == "__main__":
    main()

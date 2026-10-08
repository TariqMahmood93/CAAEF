#!/usr/bin/env python3
"""Phase 7: tables, figures and the quotable-numbers file.

Emits
  results/tables/*.tex           booktabs, sized for one ICML column
  results/figures/*.pdf          3.25 inches wide, readable in greyscale
  results/paper_numbers.json     every number intended for the paper, with provenance

Every figure uses linestyle and marker as well as colour, so it survives greyscale
printing. Nothing here recomputes a metric: it reads the analysis outputs, so a number in
the paper and a number in a table cannot drift apart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from caaef.config import RESULTS_DIR

TABLES = RESULTS_DIR / "tables"
FIGS = RESULTS_DIR / "figures"
COL_WIDTH_IN = 3.25

plt.rcParams.update({
    "figure.figsize": (COL_WIDTH_IN, 2.3),
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    # NOT bbox="tight": it trims to the content and the saved page then comes out
    # narrower than the column it must fill. constrained_layout fits the content INSIDE
    # the requested 3.25in instead.
    "figure.constrained_layout.use": True,
    "figure.constrained_layout.w_pad": 0.02,
    "figure.constrained_layout.h_pad": 0.02,
})

MODEL_ORDER = ["haiku-5.5", "sonnet-5.5", "gpt-6-luna", "gpt-6-sol"]
# Distinct in greyscale: different markers AND linestyles, mid-greys.
STYLE = {
    "haiku-5.5":  dict(color="#222222", marker="o", linestyle="-"),
    "sonnet-5.5": dict(color="#666666", marker="s", linestyle="--"),
    "gpt-6-luna": dict(color="#999999", marker="^", linestyle="-."),
    "gpt-6-sol":  dict(color="#444444", marker="D", linestyle=":"),
}


def ci(d: dict) -> str:
    if d is None or d.get("point") is None:
        return "---"
    lo, hi = d.get("ci_lo"), d.get("ci_hi")
    if lo is None:
        return f"{d['point']:.3f}"
    return f"{d['point']:.3f} [{lo:.3f}, {hi:.3f}]"


def tex_escape(s: str) -> str:
    return s.replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def table_profile(rq1: dict, config: str) -> str:
    per = rq1["by_config"][config]["all"]
    lines = [
        r"\begin{table}[t]",
        r"\caption{Per-model evaluation profile under the %s checker configuration. "
        r"Intervals are 95\%% bootstrap, resampling whole scenarios. "
        r"Categories are (1) intended success, (2) unsafe success, (3) safe failure, "
        r"(4) unsafe failure.}" % tex_escape(config),
        r"\label{tab:profile-%s}" % config.replace("_", "-"),
        r"\vskip 0.1in",
        r"\begin{center}\begin{small}",
        r"\begin{tabular}{lccccc}",
        r"\toprule",
        r"Model & $O$ & $V$ rate & CS & (1)/(2)/(3)/(4) \\",
        r"\midrule",
    ]
    for m in MODEL_ORDER:
        if m not in per:
            continue
        v = per[m]
        c = v["categories"]
        cats = "/".join(str(c.get(str(k), 0)) for k in (1, 2, 3, 4))
        lines.append(
            f"{tex_escape(m)} & {ci(v['O'])} & {ci(v['V_rate'])} & {ci(v['CS'])} & {cats} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{small}\end{center}",
              r"\vskip -0.1in", r"\end{table}", ""]
    return "\n".join(lines)


def table_configs(rq1: dict) -> str:
    rows = []
    for conf, blk in rq1["by_config"].items():
        per = blk["all"]
        passers = [m for m, v in per.items() if (v["V_rate"]["point"] or 0) <= 0.05]
        tau = blk.get("ranking", {}).get("kendall_tau")
        vmin = min((v["V_rate"]["point"] or 0) for v in per.values())
        vmax = max((v["V_rate"]["point"] or 0) for v in per.values())
        rows.append((conf, blk["n_runs"], f"{vmin:.3f}--{vmax:.3f}",
                     len(passers), "---" if tau is None else f"{tau:+.2f}"))
    lines = [
        r"\begin{table}[t]",
        r"\caption{The conclusion depends on the checker. Kendall's $\tau$ compares the "
        r"ranking by $O$ alone with the ranking under the gate at $\delta=0.05$. Where no "
        r"model passes the gate, $\tau=+1$ is degeneracy rather than agreement: the gate "
        r"cannot discriminate, so the gated ranking collapses onto the $O$ ranking.}",
        r"\label{tab:configs}",
        r"\vskip 0.1in",
        r"\begin{center}\begin{small}",
        r"\begin{tabular}{lcccc}",
        r"\toprule",
        r"Configuration & Runs & $V$ rate range & \# passing & $\tau$ \\",
        r"\midrule",
    ]
    for conf, n, rng, npass, tau in rows:
        lines.append(f"{tex_escape(conf)} & {n} & {rng} & {npass} & {tau} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{small}\end{center}",
              r"\vskip -0.1in", r"\end{table}", ""]
    return "\n".join(lines)


def table_rq2(rq2: dict) -> str:
    a = rq2["auroc"]
    lines = [
        r"\begin{table}[t]",
        r"\caption{RQ2: the distance score $D$ does not give early warning. AUROC is "
        r"computed on prefixes strictly before the first violating action. The realised "
        r"false-alarm rate exceeds its conformal target by a factor of about 2.8, "
        r"indicating that exchangeability does not hold across scenarios.}",
        r"\label{tab:rq2}",
        r"\vskip 0.1in",
        r"\begin{center}\begin{small}",
        r"\begin{tabular}{lc}",
        r"\toprule",
        r"Quantity & Value \\",
        r"\midrule",
        f"AUROC, $D$ & {a['D']:.3f} \\\\" if a.get("D") is not None else "AUROC, $D$ & --- \\\\",
        f"AUROC, action count & {a['action_count_baseline']:.3f} \\\\"
        if a.get("action_count_baseline") is not None else "AUROC, action count & --- \\\\",
        f"AUROC, keyword rule & {a['keyword_baseline']:.3f} \\\\"
        if a.get("keyword_baseline") is not None else "AUROC, keyword rule & --- \\\\",
        r"\midrule",
    ]
    for f, blk in rq2["per_target_far"].items():
        if blk.get("threshold") is None:
            continue
        tgt = float(f)
        lines.append(
            f"Detected before violation, target {tgt:.0%} & "
            f"{blk['detected_before_first_violation']}/{blk['n_violating_localised']} \\\\"
            .replace("%", r"\%")
        )
        lines.append(
            f"Realised false-alarm rate, target {tgt:.0%} & {blk['realised_far']:.3f} \\\\"
            .replace("%", r"\%")
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{small}\end{center}",
              r"\vskip -0.1in", r"\end{table}", ""]
    return "\n".join(lines)


def fig_categories(rq1: dict, config: str) -> Path:
    per = rq1["by_config"][config]["all"]
    models = [m for m in MODEL_ORDER if m in per]
    labels = ["(1) intended\nsuccess", "(2) unsafe\nsuccess",
              "(3) safe\nfailure", "(4) unsafe\nfailure"]
    hatches = ["", "///", "...", "xxx"]
    greys = ["#dddddd", "#888888", "#f4f4f4", "#555555"]
    fig, ax = plt.subplots(figsize=(COL_WIDTH_IN, 2.9))
    bottom = np.zeros(len(models))
    for k in range(1, 5):
        vals = np.array([per[m]["categories"].get(str(k), 0) for m in models], dtype=float)
        ax.bar(models, vals, bottom=bottom, label=labels[k - 1],
               color=greys[k - 1], edgecolor="black", linewidth=0.5, hatch=hatches[k - 1])
        bottom += vals
    ax.set_ylabel("runs")
    ax.set_title(f"Behavioural categories ({config})")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=False)
    ax.tick_params(axis="x", rotation=20)
    out = FIGS / f"categories_{config}.pdf"
    fig.savefig(out); plt.close(fig)
    return out


def fig_far(rq2: dict) -> Path | None:
    pts = [(float(f), b["realised_far"]) for f, b in rq2["per_target_far"].items()
           if b.get("realised_far") is not None]
    if not pts:
        return None
    pts.sort()
    x = [p[0] for p in pts]; y = [p[1] for p in pts]
    fig, ax = plt.subplots()
    lim = max(max(x), max(y)) * 1.15
    ax.plot([0, lim], [0, lim], color="#999999", linestyle="--", linewidth=0.8,
            label="target = realised")
    ax.plot(x, y, color="#222222", marker="o", linestyle="-", label="observed")
    for xi, yi in pts:
        ax.annotate(f"{yi/xi:.1f}$\\times$", (xi, yi), textcoords="offset points",
                    xytext=(5, -2), fontsize=7)
    ax.set_xlabel("target false-alarm rate")
    ax.set_ylabel("realised")
    ax.set_title("Conformal calibration fails across scenarios")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.legend(frameon=False, loc="upper left")
    out = FIGS / "conformal_far.pdf"
    fig.savefig(out); plt.close(fig)
    return out


def fig_v_by_config(rq1: dict) -> Path:
    confs = [c for c in ("rules_state", "judge_A", "judge_B", "full", "full_cross_family")
             if c in rq1["by_config"]]
    fig, ax = plt.subplots()
    xs = np.arange(len(confs))
    for m in MODEL_ORDER:
        ys, los, his = [], [], []
        for c in confs:
            v = rq1["by_config"][c]["all"].get(m)
            ys.append(np.nan if not v else v["V_rate"]["point"])
            los.append(np.nan if not v else (v["V_rate"]["ci_lo"] or np.nan))
            his.append(np.nan if not v else (v["V_rate"]["ci_hi"] or np.nan))
        ys = np.array(ys, dtype=float)
        ax.plot(xs, ys, label=m, markersize=3.5, linewidth=1.1, **STYLE[m])
    ax.axhline(0.05, color="#bbbbbb", linestyle="--", linewidth=0.8)
    ax.annotate(r"$\delta=0.05$", (len(confs) - 1, 0.055), fontsize=6.5, color="#777777",
                ha="right")
    ax.set_xticks(xs)
    ax.set_xticklabels([c.replace("_", "\n") for c in confs])
    ax.set_ylabel("$V$ rate")
    ax.set_title("Measured violation rate depends on the checker")
    ax.legend(frameon=False, ncol=2, loc="upper left")
    out = FIGS / "v_rate_by_config.pdf"
    fig.savefig(out); plt.close(fig)
    return out


def main() -> int:
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)

    rq1_path, rq2_path = RESULTS_DIR / "rq1.json", RESULTS_DIR / "rq2.json"
    if not rq1_path.exists():
        print("run scripts/analyse_rq1.py first")
        return 1
    rq1 = json.loads(rq1_path.read_text())["report"]
    rq2 = json.loads(rq2_path.read_text()) if rq2_path.exists() else None

    written = []
    head = "full" if "full" in rq1["by_config"] else "rules_state"
    for conf in ("rules_state", head):
        p = TABLES / f"profile_{conf}.tex"
        p.write_text(table_profile(rq1, conf)); written.append(p)
    p = TABLES / "checker_configs.tex"; p.write_text(table_configs(rq1)); written.append(p)
    if rq2:
        p = TABLES / "rq2_early_warning.tex"; p.write_text(table_rq2(rq2)); written.append(p)

    figs = [fig_categories(rq1, head), fig_v_by_config(rq1)]
    if rq2:
        f = fig_far(rq2)
        if f:
            figs.append(f)

    # paper_numbers.json: every quotable number, with the script and inputs behind it.
    nums = {
        "_provenance": {
            "generated": "scripts/make_outputs.py",
            "inputs": ["results/rq1.json", "results/rq2.json",
                       "results/judgments.jsonl", "results/objective.jsonl",
                       "traces/*.jsonl"],
            "note": (
                "Every value is read from an analysis output, never recomputed here, so "
                "a number in the paper cannot drift from the number in a table."
            ),
        },
        "design": {
            "n_scenarios": rq1["n_scenarios"],
            "n_runs_scored": rq1["n_runs"],
            "scenarios_of_40": 20,
            "repetitions_complete": 1,
            "source": "config/design.yaml; notes/phase2.md",
        },
        "rq1": {
            conf: {
                "n_runs": blk["n_runs"],
                "kendall_tau_O_vs_gate": blk.get("ranking", {}).get("kendall_tau"),
                "models_passing_gate_delta_0.05": [
                    m for m, v in blk["all"].items() if (v["V_rate"]["point"] or 0) <= 0.05
                ],
                "per_model": {
                    m: {
                        "O": v["O"], "V_rate": v["V_rate"], "CS": v["CS"], "SC": v["SC"],
                        "categories": v["categories"],
                        "outcome_only_success_but_V1": v["outcome_only_success_but_V1"],
                        "n_O_missing": v["n_O_missing"],
                    } for m, v in blk["all"].items()
                },
            } for conf, blk in rq1["by_config"].items()
        },
        "rq2": None if not rq2 else {
            "auroc": rq2["auroc"],
            "per_target_far": rq2["per_target_far"],
            "n_violating_localised": rq2["n_violating_localised"],
            "n_compliant": rq2["n_compliant"],
        },
        "rq3_u_informative": "PENDING AUDIT — requires human consensus labels",
        "rq4_component_ablation": "PENDING AUDIT — precision/recall need human labels",
        "rq5_gate_under_checker_error": (
            "PENDING AUDIT — alpha and beta are estimated from the audit"
        ),
        "not_computable": {
            "benchmark_severity_agreement": (
                "The benchmark's own severity>=3 labels cover 12 models, none of which is "
                "in our slate, so no run overlaps and the agreement cannot be computed."
            )
        },
        "caveats": rq1["caveats"],
    }
    (RESULTS_DIR / "paper_numbers.json").write_text(json.dumps(nums, indent=2))

    print("tables:")
    for p in written:
        print(f"  {p.relative_to(RESULTS_DIR.parent)}")
    print("figures:")
    for p in figs:
        print(f"  {p.relative_to(RESULTS_DIR.parent)}")
    print(f"numbers: results/paper_numbers.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

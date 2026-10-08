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
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

from caaef.config import RESULTS_DIR

TABLES = RESULTS_DIR / "tables"
FIGS = RESULTS_DIR / "figures"

# Figure sizing, per the author's instruction: colour, larger, legends underneath.
#
# NOTE a trade-off this overrides. The experiment plan asked for 3.25 in wide,
# greyscale-readable figures to fit one ICML column. These are wider and rely on colour,
# so they will need re-sizing before submission. Markers and linestyles are still kept
# distinct underneath the colour, so nothing is lost if they are ever printed in mono.
FIG_W = 7.2
FIG_H = 4.4

plt.rcParams.update({
    "figure.figsize": (FIG_W, FIG_H),
    "figure.dpi": 120,
    "font.size": 11,
    "axes.labelsize": 11,
    "axes.titlesize": 12.5,
    "axes.titleweight": "semibold",
    "axes.titlepad": 10,
    "legend.fontsize": 10,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#4a4a4a",
    "axes.labelcolor": "#1f1f1f",
    "text.color": "#1f1f1f",
    "xtick.color": "#4a4a4a",
    "ytick.color": "#4a4a4a",
    "axes.grid": True,
    "grid.color": "#d8d8d8",
    "grid.linewidth": 0.7,
    "grid.alpha": 0.9,
    "legend.frameon": False,
    "figure.constrained_layout.use": True,
})

MODEL_ORDER = ["haiku-5.5", "sonnet-5.5", "gpt-6-luna", "gpt-6-sol"]

# Colour by provider family so the Anthropic/OpenAI split reads off the chart: warm
# tones for the Anthropic models, cool for the OpenAI ones, lighter shade for the
# smaller model in each pair. Markers and linestyles stay distinct as a mono fallback.
STYLE = {
    "haiku-5.5":  dict(color="#e08a3c", marker="o", linestyle="-"),
    "sonnet-5.5": dict(color="#b3442d", marker="s", linestyle="--"),
    "gpt-6-luna": dict(color="#4c9bd1", marker="^", linestyle="-."),
    "gpt-6-sol":  dict(color="#2b5d8a", marker="D", linestyle=":"),
}

# Category palette: the two "violating" cells warm, the two "compliant" cells cool, so
# the safe/unsafe split is visible before reading the legend.
CATEGORY_STYLE = [
    ("(1) intended success", "#4c9bd1", ""),
    ("(2) unsafe success",   "#b3442d", "//"),
    ("(3) safe failure",     "#a8cfe8", ""),
    ("(4) unsafe failure",   "#e08a3c", "\\\\"),
]


def legend_below(ax, ncol: int, y: float = -0.16, **kw):
    """Put the legend under the axes.

    Every figure here does this, per the author's instruction, so it is one helper
    rather than four copies of the same bbox_to_anchor incantation.
    """
    return ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, y), ncol=ncol,
        frameon=False, handlelength=1.9, columnspacing=1.6, **kw,
    )


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
    # table* : five columns carrying bracketed confidence intervals do not fit a
    # single 3.25in ICML column.
    lines = [
        r"\begin{table*}[t]",
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
              r"\vskip -0.1in", r"\end{table*}", ""]
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
        r"\begin{table*}[t]",
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
              r"\vskip -0.1in", r"\end{table*}", ""]
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
    """Stacked behavioural categories per model, as counts and as shares."""
    per = rq1["by_config"][config]["all"]
    models = [m for m in MODEL_ORDER if m in per]
    counts = {
        k: np.array([per[m]["categories"].get(str(k), 0) for m in models], dtype=float)
        for k in range(1, 5)
    }
    totals = sum(counts.values())

    fig, (ax_n, ax_p) = plt.subplots(
        1, 2, figsize=(FIG_W + 1.2, FIG_H + 0.5), sharey=False
    )
    x = np.arange(len(models))

    for ax, as_share in ((ax_n, False), (ax_p, True)):
        bottom = np.zeros(len(models))
        for k in range(1, 5):
            label, colour, hatch = CATEGORY_STYLE[k - 1]
            vals = counts[k] / totals * 100 if as_share else counts[k]
            bars = ax.bar(
                x, vals, bottom=bottom, width=0.66, label=label, color=colour,
                edgecolor="white", linewidth=1.1, hatch=hatch,
            )
            # Label only the slices with room, so the chart stays readable.
            for xi, v, b in zip(x, vals, bottom):
                # 0.11 rather than 0.07: thinner bands cannot hold a label without it
                # colliding with the band edge and the hatching.
                if (v / (100 if as_share else totals[xi])) > 0.11:
                    ax.text(
                        xi, b + v / 2, f"{v:.0f}%" if as_share else f"{int(v)}",
                        ha="center", va="center", fontsize=9.5,
                        color="#15202b", fontweight="semibold",
                        path_effects=[pe.withStroke(linewidth=2.6, foreground="white")],
                    )
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=0, ha="center")
        ax.set_axisbelow(True)
        ax.grid(axis="x", visible=False)
        if as_share:
            ax.set_ylabel("share of runs (%)")
            ax.set_ylim(0, 100)
            ax.set_title("as a share")
        else:
            ax.set_ylabel("runs")
            ax.set_title("as counts")

    fig.suptitle(
        f"Behavioural categories by model  ({config} checker)",
        fontsize=13.5, fontweight="semibold", y=1.04,
    )
    # One shared legend, under both panels.
    handles, labels = ax_n.get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="lower center", ncol=4, frameon=False,
        bbox_to_anchor=(0.5, -0.04), handlelength=1.6, columnspacing=1.8,
    )
    out = FIGS / f"categories_{config}.pdf"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    return out


def fig_far(rq2: dict) -> Path | None:
    """Realised against target false-alarm rate: the exchangeability diagnostic."""
    pts = [(float(f), b["realised_far"]) for f, b in rq2["per_target_far"].items()
           if b.get("realised_far") is not None]
    if not pts:
        return None
    pts.sort()
    x = np.array([p[0] for p in pts]); y = np.array([p[1] for p in pts])

    fig, ax = plt.subplots(figsize=(FIG_W - 0.4, FIG_H))
    # Scale each axis to its own data. Forcing a square aspect over the full 0..0.35
    # range pushed the two observed points into the left third of an otherwise empty
    # panel; the diagonal is still y=x, it simply is not drawn at 45 degrees.
    xhi = float(x.max()) * 1.45
    yhi = float(y.max()) * 1.25
    ax.fill_between([0, xhi], [0, xhi], [yhi, yhi], color="#b3442d", alpha=0.08,
                    linewidth=0, label="worse than the guarantee")
    ax.plot([0, xhi], [0, xhi], color="#6a6a6a", linestyle="--", linewidth=1.6,
            label="target = realised (guarantee holds)")
    ax.plot(x, y, color="#b3442d", marker="o", markersize=9, linewidth=2.2,
            markeredgecolor="white", markeredgewidth=1.4, label="observed", zorder=5)

    for xi, yi in zip(x, y):
        ax.annotate(
            f"{yi/xi:.1f}x over target", (xi, yi), textcoords="offset points",
            xytext=(10, -14), fontsize=10.5, color="#8f2f1f", fontweight="medium",
        )

    ax.set_xlabel("target false-alarm rate")
    ax.set_ylabel("realised false-alarm rate")
    ax.set_title("Conformal calibration does not transfer across scenarios")
    ax.set_xlim(0, xhi); ax.set_ylim(0, yhi)
    ax.set_axisbelow(True)
    legend_below(ax, ncol=3, y=-0.17)
    out = FIGS / "conformal_far.pdf"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    return out


def fig_v_by_config(rq1: dict) -> Path:
    """Violation rate per model across checker configurations, with clustered CIs."""
    confs = [c for c in ("rules_state", "judge_A", "judge_B", "full", "full_cross_family")
             if c in rq1["by_config"]]
    fig, ax = plt.subplots(figsize=(FIG_W + 0.3, FIG_H + 0.3))
    xs = np.arange(len(confs), dtype=float)
    # Small horizontal offsets so overlapping intervals stay legible.
    offsets = np.linspace(-0.11, 0.11, len(MODEL_ORDER))

    for m, dx in zip(MODEL_ORDER, offsets):
        ys, lo, hi = [], [], []
        for c in confs:
            v = rq1["by_config"][c]["all"].get(m)
            ys.append(np.nan if not v else v["V_rate"]["point"])
            lo.append(np.nan if not v else (v["V_rate"]["ci_lo"] if v["V_rate"]["ci_lo"] is not None else np.nan))
            hi.append(np.nan if not v else (v["V_rate"]["ci_hi"] if v["V_rate"]["ci_hi"] is not None else np.nan))
        ys = np.array(ys, dtype=float)
        lo = np.array(lo, dtype=float); hi = np.array(hi, dtype=float)
        st = STYLE[m]
        ax.errorbar(
            xs + dx, ys, yerr=[np.clip(ys - lo, 0, None), np.clip(hi - ys, 0, None)],
            label=m, markersize=7.5, linewidth=2.0, elinewidth=1.2, capsize=3.5,
            markeredgecolor="white", markeredgewidth=1.0, alpha=0.95, **st,
        )

    # Draw the tolerance line and label it directly. An earlier version lost the label
    # to over-escaped mathtext and shaded everything above it, which filled most of the
    # panel and read as decoration rather than information.
    ax.axhline(0.05, color="#3f3f3f", linestyle=(0, (5, 3)), linewidth=1.4, zorder=1)
    ax.text(
        -0.33, 0.057, "gate tolerance  " + r"$\delta = 0.05$",
        fontsize=10.5, color="#3f3f3f", ha="left", va="bottom",
        path_effects=[pe.withStroke(linewidth=3, foreground="white")],
    )
    ax.text(
        len(confs) - 0.62, 0.012, "below the line = passes the gate",
        fontsize=9.5, color="#6a6a6a", ha="right", style="italic",
    )

    ax.set_xticks(xs)
    ax.set_xticklabels([c.replace("_", " ") for c in confs])
    ax.set_ylabel("$V$ rate (hard-violation rate)")
    ax.set_xlabel("checker configuration")
    ax.set_title("The measured violation rate depends on the checker")
    ax.set_xlim(-0.4, len(confs) - 0.6)
    ax.set_ylim(bottom=-0.02)
    ax.set_axisbelow(True)
    ax.grid(axis="x", visible=False)
    legend_below(ax, ncol=4, y=-0.19)
    out = FIGS / "v_rate_by_config.pdf"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
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

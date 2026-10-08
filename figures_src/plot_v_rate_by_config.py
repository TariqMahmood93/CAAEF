"""Violation rate by checker configuration (RQ1).

Standalone: run it directly ("python plot_v_rate_by_config.py") with only matplotlib + numpy.
The data is inlined below exactly as produced by the analysis, so this file needs
nothing else from the project.

Source: results/rq1.json -> by_config[*].all[*].V_rate
Generated from the CAAEF study, 2026-10-08.
"""

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

OUT_STEM = "v_rate_by_config"

plt.rcParams.update({
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


# Hard-violation rate per model across checker configurations, with 95% bootstrap
# intervals that resample whole scenarios. [point, ci_lo, ci_hi] per configuration.
CONFIGS = ['rules_state', 'judge_A', 'judge_B', 'full', 'full_cross_family']
MODELS = ['haiku-5.5', 'sonnet-5.5', 'gpt-6-luna', 'gpt-6-sol']
SERIES = {
    'haiku-5.5': [[0.028846153846153848, 0.0, 0.08823529411764706], [0.0375, 0.0, 0.075], [0.2, 0.07468750000000028, 0.35], [0.1625, 0.05, 0.3], [0.1625, 0.05, 0.3]],
    'sonnet-5.5': [[0.03076923076923077, 0.0, 0.09523809523809523], [0.1, 0.0, 0.25], [0.3, 0.125, 0.5], [0.3, 0.125, 0.5], [0.3, 0.125, 0.5]],
    'gpt-6-luna': [[0.125, 0.015625, 0.27586206896551724], [0.0, 0.0, 0.0], [0.075, 0.0, 0.15], [0.175, 0.05, 0.325], [0.125, 0.0, 0.275]],
    'gpt-6-sol': [[0.09375, 0.015151515151515152, 0.1935483870967742], [0.025, 0.0, 0.075], [0.1, 0.0, 0.225], [0.225, 0.1, 0.375], [0.175, 0.05, 0.325]],
}
DELTA = 0.05  # gate tolerance

STYLE = {
    "haiku-5.5":  dict(color="#e08a3c", marker="o", linestyle="-"),
    "sonnet-5.5": dict(color="#b3442d", marker="s", linestyle="--"),
    "gpt-6-luna": dict(color="#4c9bd1", marker="^", linestyle="-."),
    "gpt-6-sol":  dict(color="#2b5d8a", marker="D", linestyle=":"),
}


def make_figure():
    fig, ax = plt.subplots(figsize=(7.5, 4.7))
    xs = np.arange(len(CONFIGS), dtype=float)
    offsets = np.linspace(-0.11, 0.11, len(MODELS))

    for m, dx in zip(MODELS, offsets):
        pts = SERIES[m]
        ys = np.array([np.nan if p is None else p[0] for p in pts], float)
        lo = np.array([np.nan if p is None or p[1] is None else p[1] for p in pts], float)
        hi = np.array([np.nan if p is None or p[2] is None else p[2] for p in pts], float)
        ax.errorbar(xs + dx, ys,
                    yerr=[np.clip(ys - lo, 0, None), np.clip(hi - ys, 0, None)],
                    label=m, markersize=7.5, linewidth=2.0, elinewidth=1.2,
                    capsize=3.5, markeredgecolor="white", markeredgewidth=1.0,
                    alpha=0.95, **STYLE[m])

    ax.axhline(DELTA, color="#3f3f3f", linestyle=(0, (5, 3)), linewidth=1.4, zorder=1)
    ax.text(-0.33, DELTA + 0.007, "gate tolerance  " + r"$\delta = 0.05$",
            fontsize=10.5, color="#3f3f3f", ha="left", va="bottom",
            path_effects=[pe.withStroke(linewidth=3, foreground="white")])
    ax.text(len(CONFIGS) - 0.62, 0.012, "below the line = passes the gate",
            fontsize=9.5, color="#6a6a6a", ha="right", style="italic")

    ax.set_xticks(xs)
    ax.set_xticklabels([c.replace("_", " ") for c in CONFIGS])
    ax.set_ylabel("$V$ rate (hard-violation rate)")
    ax.set_xlabel("checker configuration")
    ax.set_title("The measured violation rate depends on the checker")
    ax.set_xlim(-0.4, len(CONFIGS) - 0.6)
    ax.set_ylim(bottom=-0.02)
    ax.set_axisbelow(True)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.19), ncol=4,
              frameon=False, handlelength=1.9, columnspacing=1.6)
    return fig


if __name__ == "__main__":
    fig = make_figure()
    fig.savefig(OUT_STEM + ".pdf", bbox_inches="tight")
    fig.savefig(OUT_STEM + ".png", bbox_inches="tight", dpi=200)
    print("wrote " + OUT_STEM + ".pdf and " + OUT_STEM + ".png")
    plt.show()

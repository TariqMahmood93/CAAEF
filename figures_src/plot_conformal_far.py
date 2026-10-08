"""Conformal calibration diagnostic (RQ2).

Standalone: run it directly ("python plot_conformal_far.py") with only matplotlib + numpy.
The data is inlined below exactly as produced by the analysis, so this file needs
nothing else from the project.

Source: results/rq2.json -> per_target_far
Generated from the CAAEF study, 2026-10-08.
"""

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

OUT_STEM = "conformal_far"

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


# Target against realised false-alarm rate for the split-conformal threshold.
# A point above the diagonal means the conformal guarantee did not hold.
POINTS = [(0.05, 0.14285714285714285), (0.1, 0.2698412698412698)]   # (target, realised)


def make_figure():
    x = np.array([p[0] for p in POINTS], float)
    y = np.array([p[1] for p in POINTS], float)

    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    # Each axis is scaled to its own data: forcing a square over the full range pushed
    # both observations into a corner. The dashed line is still y = x.
    xhi, yhi = float(x.max()) * 1.45, float(y.max()) * 1.25

    ax.fill_between([0, xhi], [0, xhi], [yhi, yhi], color="#b3442d", alpha=0.08,
                    linewidth=0, label="worse than the guarantee")
    ax.plot([0, xhi], [0, xhi], color="#6a6a6a", linestyle="--", linewidth=1.6,
            label="target = realised (guarantee holds)")
    ax.plot(x, y, color="#b3442d", marker="o", markersize=9, linewidth=2.2,
            markeredgecolor="white", markeredgewidth=1.4, label="observed", zorder=5)

    for xi, yi in zip(x, y):
        ax.annotate(f"{yi/xi:.1f}x over target", (xi, yi), textcoords="offset points",
                    xytext=(10, -14), fontsize=10.5, color="#8f2f1f", fontweight="medium")

    ax.set_xlabel("target false-alarm rate")
    ax.set_ylabel("realised false-alarm rate")
    ax.set_title("Conformal calibration does not transfer across scenarios")
    ax.set_xlim(0, xhi); ax.set_ylim(0, yhi)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3,
              frameon=False, handlelength=1.9, columnspacing=1.6)
    return fig


if __name__ == "__main__":
    fig = make_figure()
    fig.savefig(OUT_STEM + ".pdf", bbox_inches="tight")
    fig.savefig(OUT_STEM + ".png", bbox_inches="tight", dpi=200)
    print("wrote " + OUT_STEM + ".pdf and " + OUT_STEM + ".png")
    plt.show()

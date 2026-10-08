"""Behavioural categories by model (RQ1).

Standalone: run it directly ("python plot_categories.py") with only matplotlib + numpy.
The data is inlined below exactly as produced by the analysis, so this file needs
nothing else from the project.

Source: results/rq1.json -> by_config.full.all[*].categories
Generated from the CAAEF study, 2026-10-08.
"""

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

OUT_STEM = "categories_full"

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


# Behavioural categories per model, full checker protocol.
# (1) intended success  (2) unsafe success  (3) safe failure  (4) unsafe failure
MODELS = ['haiku-5.5', 'sonnet-5.5', 'gpt-6-luna', 'gpt-6-sol']
COUNTS = {
    'haiku-5.5': {1: 1, 2: 3, 3: 46, 4: 6},
    'sonnet-5.5': {1: 1, 2: 2, 3: 20, 4: 5},
    'gpt-6-luna': {1: 3, 2: 2, 3: 19, 4: 4},
    'gpt-6-sol': {1: 3, 2: 2, 3: 18, 4: 5},
}

CATEGORY_STYLE = [
    ("(1) intended success", "#4c9bd1", ""),
    ("(2) unsafe success",   "#b3442d", "//"),
    ("(3) safe failure",     "#a8cfe8", ""),
    ("(4) unsafe failure",   "#e08a3c", "\\\\"),
]


def make_figure():
    models = MODELS
    counts = {k: np.array([COUNTS[m][k] for m in models], float) for k in range(1, 5)}
    totals = sum(counts.values())

    fig, (ax_n, ax_p) = plt.subplots(1, 2, figsize=(8.4, 4.9))
    x = np.arange(len(models))

    for ax, as_share in ((ax_n, False), (ax_p, True)):
        bottom = np.zeros(len(models))
        for k in range(1, 5):
            label, colour, hatch = CATEGORY_STYLE[k - 1]
            vals = counts[k] / totals * 100 if as_share else counts[k]
            ax.bar(x, vals, bottom=bottom, width=0.66, label=label, color=colour,
                   edgecolor="white", linewidth=1.1, hatch=hatch)
            for xi, v, b in zip(x, vals, bottom):
                # Only label bands with room; thinner ones collide with the hatching.
                if (v / (100 if as_share else totals[xi])) > 0.11:
                    ax.text(xi, b + v / 2,
                            f"{v:.0f}%" if as_share else f"{int(v)}",
                            ha="center", va="center", fontsize=9.5,
                            color="#15202b", fontweight="semibold",
                            path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(models)
        ax.set_axisbelow(True)
        ax.grid(axis="x", visible=False)
        if as_share:
            ax.set_ylabel("share of runs (%)"); ax.set_ylim(0, 100); ax.set_title("as a share")
        else:
            ax.set_ylabel("runs"); ax.set_title("as counts")

    fig.suptitle("Behavioural categories by model  (full checker)",
                 fontsize=13.5, fontweight="semibold", y=1.04)
    handles, labels = ax_n.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, -0.04), handlelength=1.6, columnspacing=1.8)
    return fig


if __name__ == "__main__":
    fig = make_figure()
    fig.savefig(OUT_STEM + ".pdf", bbox_inches="tight")
    fig.savefig(OUT_STEM + ".png", bbox_inches="tight", dpi=200)
    print("wrote " + OUT_STEM + ".pdf and " + OUT_STEM + ".png")
    plt.show()

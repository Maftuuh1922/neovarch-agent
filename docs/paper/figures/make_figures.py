"""Figures for the Neovarch Agent technical report.

    python3 docs/paper/figures/make_figures.py

Reads only the CSV files in docs/paper/data/ (copied from the benchmark logs) and the replay numbers
published in docs/codemode.md. Writes vector PDFs next to this script. Requires matplotlib.
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"

RED, DARK, GREY, LIGHT, INK = "#C8101A", "#8F0A0A", "#7A7A7A", "#BDBDBD", "#1A1A1A"
plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": INK,
    "xtick.color": INK, "ytick.color": INK, "pdf.fonttype": 42,
})


def bench10():
    rows = list(csv.DictReader(open(DATA / "bench10_combined.csv")))
    short = {"Neovarch lean (codemode)": "NV-cm", "Neovarch lean (parallel)": "NV-par",
             "Hermes Agent": "Hermes", "Codex CLI": "Codex", "Pi": "Pi"}
    names = [short[r["arm"]] for r in rows]
    colors = [RED, DARK, GREY, LIGHT, LIGHT]
    panels = [
        ("Passed (of 20)", [int(r["pass"]) for r in rows], "{:.0f}"),
        ("Model calls", [int(r["model_calls"]) for r in rows], "{:.0f}"),
        ("Prompt tokens (k)", [int(r["prompt_tokens"]) / 1000 for r in rows], "{:.0f}k"),
        ("Equiv. cost (USD)", [float(r["equiv_usd"]) for r in rows], "{:.3f}"),
        ("Wall time (s)", [int(r["wall_s"]) for r in rows], "{:.0f}"),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(7.2, 2.2))
    for ax, (title, vals, fmt) in zip(axes, panels):
        bars = ax.bar(range(len(vals)), vals, color=colors, edgecolor=INK, linewidth=0.4)
        ax.set_title(title)
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(names, rotation=45, ha="right", fontsize=6.8)
        top = max(vals)
        ax.set_ylim(0, top * 1.22)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + top * 0.02, fmt.format(v),
                    ha="center", va="bottom", fontsize=5.6)
        ax.tick_params(axis="y", labelsize=6.5)
    fig.tight_layout(w_pad=0.6)
    fig.savefig(HERE / "bench10.pdf")
    plt.close(fig)


def hard_r1():
    rows = list(csv.DictReader(open(DATA / "hard_r1.csv")))
    tasks = ["hunt-csv", "hunt-atomic-place", "refactor-unify-revenue"]
    agents = [("neovarch", "Neovarch", RED), ("hermes", "Hermes", GREY), ("pi", "Pi", LIGHT), ("codex", "Codex CLI", "#FFFFFF")]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4))
    w = 0.2
    for ax, (key, title, scale) in zip(axes, [("model_calls", "Model calls per task", 1),
                                              ("prompt_tokens", "Prompt tokens per task (thousands)", 1000)]):
        top = 0
        for i, (a, label, col) in enumerate(agents):
            for j, t in enumerate(tasks):
                r = next((x for x in rows if x["agent"] == a and x["task"] == t), None)
                x = j + (i - 1.5) * w
                if r is None:
                    ax.text(x, 0.5, "not run", rotation=90, ha="center", va="bottom", fontsize=5.8, color=GREY)
                    continue
                v = float(r[key]) / scale
                top = max(top, v)
                ok = r["pass"] == "True"
                ax.bar(x, v, w, color=col, edgecolor=INK, linewidth=0.5, hatch=None if ok else "////",
                       label=label if j == 0 else None)
                if not ok:
                    ax.text(x, v, " fail\n(timeout)", ha="center", va="bottom", fontsize=5.6)
        ax.set_xticks(range(len(tasks)))
        ax.set_xticklabels([t.replace("-", "-\n", 1) for t in tasks], fontsize=7)
        ax.set_title(title)
        ax.set_ylim(0, top * 1.25)
        ax.tick_params(axis="y", labelsize=6.5)
    axes[0].legend(fontsize=6.5, frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(HERE / "hard_r1.pdf")
    plt.close(fig)


def codemode_replay():
    # docs/codemode.md, deterministic replay (scripted model), 10 tasks, 1 run per arm, 2026-10-14.
    arms = ["one tool\nper call", "parallel\nreads", "codemode"]
    calls = [57, 38, 23]
    prompt = [271819, 183668, 108389]
    uncached = [54603, 53236, 49509]
    fig, axes = plt.subplots(1, 2, figsize=(5.2, 2.0))
    cols = [LIGHT, GREY, RED]
    for ax, vals, title, fmt in [(axes[0], calls, "Model calls", "{:.0f}"),
                                 (axes[1], [p / 1000 for p in prompt], "Prompt tokens (thousands)", "{:.0f}k")]:
        bars = ax.bar(range(3), vals, color=cols, edgecolor=INK, linewidth=0.4)
        ax.set_xticks(range(3))
        ax.set_xticklabels(arms, fontsize=7)
        ax.set_title(title)
        ax.set_ylim(0, max(vals) * 1.22)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.02, fmt.format(v), ha="center",
                    va="bottom", fontsize=6.5)
    axes[1].plot(range(3), [u / 1000 for u in uncached], "o--", color=INK, ms=3, lw=0.8, label="of which uncached")
    axes[1].legend(fontsize=6.3, frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(HERE / "codemode_replay.pdf")
    plt.close(fig)


if __name__ == "__main__":
    bench10()
    hard_r1()
    codemode_replay()
    print("figures written to", HERE)

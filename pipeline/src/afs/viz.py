"""Figures for the analysis report.

All figures are generated from the same dictionaries the report tables are built
from, so a figure can never disagree with its table.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .common import FIG_DIR

PALETTE = {
    "ink": "#1F2933",
    "muted": "#6B7280",
    "grid": "#E5E7EB",
    "accent": "#1F3364",
    "accent2": "#2F6F8F",
    "warn": "#B45309",
    "bad": "#9B2226",
    "good": "#3F6F4A",
}
SERIES = ["#1F3364", "#2F6F8F", "#6B8E9B", "#B45309", "#9B2226",
          "#3F6F4A", "#7C5C8A", "#A8763E", "#4A5568", "#8FA3B0"]


def _style() -> None:
    plt.rcParams.update({
        "figure.dpi": 160,
        "savefig.dpi": 160,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.edgecolor": PALETTE["grid"],
        "axes.labelcolor": PALETTE["ink"],
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlecolor": PALETTE["ink"],
        "axes.grid": True,
        "grid.color": PALETTE["grid"],
        "grid.linewidth": 0.7,
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })


def _finish(fig, path: Path, note: str | None = None) -> str:
    if note:
        fig.text(0.01, 0.005, note, fontsize=7, color=PALETTE["muted"])
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def freq_bar(rows: list[dict], path: Path, title: str,
             xlabel: str = "Share of failure records (%)") -> str:
    """Horizontal bar with Wilson CI whiskers."""
    _style()
    rows = [r for r in rows if r["count"] > 0]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["proportion"])
    labels = [r["label"].replace("_", " ") for r in rows]
    vals = [r["proportion"] * 100 for r in rows]
    lo = [(r["proportion"] - r["ci_low"]) * 100 for r in rows]
    hi = [(r["ci_high"] - r["proportion"]) * 100 for r in rows]

    fig, ax = plt.subplots(figsize=(7.2, max(2.4, 0.42 * len(rows) + 1.2)))
    y = np.arange(len(rows))
    ax.barh(y, vals, color=PALETTE["accent"], height=0.62, alpha=0.9)
    ax.errorbar(vals, y, xerr=[lo, hi], fmt="none", ecolor=PALETTE["muted"],
                elinewidth=1, capsize=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel(xlabel)
    ax.set_title(title, loc="left")
    for i, (v, r) in enumerate(zip(vals, rows)):
        ax.text(v + max(hi) * 0.12 + 0.4, i, f"{v:.1f}%  (n={r['count']})",
                va="center", fontsize=8, color=PALETTE["ink"])
    ax.set_xlim(0, max(vals) * 1.32 if vals else 1)
    ax.grid(axis="y", visible=False)
    return _finish(fig, path, "Whiskers: Wilson 95% CI. Denominator: all retained failure records.")


def grouped_bar(categories: list[str], series: dict[str, list[float]],
                path: Path, title: str, ylabel: str = "Share (%)") -> str:
    _style()
    n_ser = max(1, len(series))
    fig, ax = plt.subplots(figsize=(8.2, 4.0))
    x = np.arange(len(categories))
    width = 0.8 / n_ser
    for i, (name, vals) in enumerate(series.items()):
        ax.bar(x + i * width - 0.4 + width / 2, vals, width,
               label=name, color=SERIES[i % len(SERIES)])
    ax.set_xticks(x)
    ax.set_xticklabels([c.replace("_", " ") for c in categories],
                       rotation=25, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path, "Percentages within each framework's retained records.")


def heatmap(matrix: list[list[float]], row_labels: list[str], col_labels: list[str],
            path: Path, title: str, cbar_label: str = "Row share (%)") -> str:
    _style()
    arr = np.asarray(matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(max(6.5, 0.85 * len(col_labels) + 3),
                                    max(3.2, 0.5 * len(row_labels) + 1.8)))
    im = ax.imshow(arr, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels([c.replace("_", " ") for c in col_labels],
                       rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels([r.replace("_", " ") for r in row_labels], fontsize=8)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            if arr[i, j] > 0:
                ax.text(j, i, f"{arr[i, j]:.0f}", ha="center", va="center",
                        fontsize=7,
                        color="white" if arr[i, j] > arr.max() * 0.6 else PALETTE["ink"])
    ax.set_title(title, loc="left")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label(cbar_label, fontsize=8)
    return _finish(fig, path, "Cells: percentage of the row's records. Empty cells omitted.")


def rate_with_ci(rows: list[dict], path: Path, title: str,
                 ylabel: str = "Rate (%)") -> str:
    _style()
    rows = [r for r in rows if r["denominator"] > 0]
    if not rows:
        return ""
    labels = [r["label"].replace("_", " ") for r in rows]
    vals = [r["proportion"] * 100 for r in rows]
    lo = [(r["proportion"] - r["ci_low"]) * 100 for r in rows]
    hi = [(r["ci_high"] - r["proportion"]) * 100 for r in rows]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    x = np.arange(len(rows))
    ax.plot(x, vals, "o-", color=PALETTE["accent"], lw=1.6, ms=6)
    ax.errorbar(x, vals, yerr=[lo, hi], fmt="none", ecolor=PALETTE["muted"],
                elinewidth=1, capsize=4)
    for i, r in enumerate(rows):
        ax.annotate(f"n={r['denominator']}", (i, vals[i]), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=7, color=PALETTE["muted"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    ax.grid(axis="x", visible=False)
    return _finish(fig, path, "Whiskers: Wilson 95% CI.")


def confusion(cm: list[list[int]], labels: list[str], path: Path,
              title: str) -> str:
    _style()
    arr = np.asarray(cm, dtype=float)
    fig, ax = plt.subplots(figsize=(max(5.5, 0.6 * len(labels) + 2.5),
                                    max(4.2, 0.5 * len(labels) + 2)))
    im = ax.imshow(arr, cmap="Greens", aspect="auto")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([l.replace("_", " ") for l in labels], rotation=40, ha="right", fontsize=7)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels([l.replace("_", " ") for l in labels], fontsize=7)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Annotated (reference)")
    ax.set_title(title, loc="left")
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            if arr[i, j] > 0:
                ax.text(j, i, int(arr[i, j]), ha="center", va="center", fontsize=7,
                        color="white" if arr[i, j] > arr.max() * 0.55 else PALETTE["ink"])
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.85)
    return _finish(fig, path, "Diagonal: agreement between automated labeller and reference annotation.")


def timeline(rows: list[dict], path: Path, title: str) -> str:
    """rows: [{label, proportions: {type: pct}}]"""
    _style()
    if not rows:
        return ""
    fig, ax = plt.subplots(figsize=(8.0, 3.6))
    x = np.arange(len(rows))
    types = sorted({t for r in rows for t in r["proportions"]})
    bottom = np.zeros(len(rows))
    for i, t in enumerate(types):
        vals = np.array([r["proportions"].get(t, 0.0) for r in rows])
        ax.bar(x, vals, bottom=bottom, label=t.replace("_", " "),
               color=SERIES[i % len(SERIES)], width=0.66)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels([str(r.get("label", r.get("year", ""))) for r in rows])
    ax.set_ylabel("Share of that year's records (%)")
    ax.set_title(title, loc="left")
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper left",
              bbox_to_anchor=(1.0, 1.0))
    ax.grid(axis="x", visible=False)
    return _finish(fig, path, "Years with fewer than 10 records are omitted.")

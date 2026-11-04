"""Statistics used by the analysis agents.

Every function returns plain Python floats and a human-readable `note`, so the
report can state exactly which test produced which number.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence

import numpy as np
from scipy import stats as sps


# --------------------------------------------------------------------------- #
# Proportions
# --------------------------------------------------------------------------- #
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Preferred over normal approximation for small n
    and for proportions near 0 or 1, which is common in this dataset."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion_row(k: int, n: int, label: str = "") -> dict:
    lo, hi = wilson_ci(k, n)
    return {
        "label": label,
        "count": k,
        "denominator": n,
        "proportion": round(k / n, 4) if n else 0.0,
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
        "ci_method": "wilson_95",
    }


def two_proportion_test(k1: int, n1: int, k2: int, n2: int) -> dict:
    """Two-sided test of equal proportions (Fisher exact for small counts)."""
    if n1 == 0 or n2 == 0:
        return {"test": "none", "p_value": None}
    table = [[k1, n1 - k1], [k2, n2 - k2]]
    if min(k1, n1 - k1, k2, n2 - k2) < 5:
        res = sps.fisher_exact(table)
        return {"test": "fisher_exact", "p_value": round(float(res.pvalue), 6),
                "odds_ratio": round(float(res.statistic), 4),
                "difference": round(k1 / n1 - k2 / n2, 4)}
    chi2, p, dof, _ = sps.chi2_contingency(table, correction=False)
    return {"test": "chi2_2x2", "chi2": round(float(chi2), 4),
            "p_value": round(float(p), 6), "dof": int(dof),
            "difference": round(k1 / n1 - k2 / n2, 4)}


# --------------------------------------------------------------------------- #
# Contingency
# --------------------------------------------------------------------------- #
def cramers_v(table: Sequence[Sequence[int]]) -> float:
    arr = np.asarray(table, dtype=float)
    if arr.sum() == 0 or min(arr.shape) < 2:
        return 0.0
    chi2 = sps.chi2_contingency(arr, correction=False)[0]
    n = arr.sum()
    return float(math.sqrt(chi2 / (n * (min(arr.shape) - 1))))


def chi2_association(rows: Iterable[str], cols: Iterable[str], label_a: str,
                     label_b: str, min_expected: float = 5.0) -> dict:
    """Chi-square test of independence for two categorical variables."""
    rows, cols = list(rows), list(cols)
    ra, ca = sorted(set(rows)), sorted(set(cols))
    idx_r = {v: i for i, v in enumerate(ra)}
    idx_c = {v: i for i, v in enumerate(ca)}
    table = np.zeros((len(ra), len(ca)), dtype=int)
    for r, c in zip(rows, cols):
        table[idx_r[r], idx_c[c]] += 1
    if table.sum() == 0:
        return {"test": "chi2", "p_value": None}
    chi2, p, dof, expected = sps.chi2_contingency(table, correction=False)
    sparse = float((expected < min_expected).mean())
    return {
        "test": "chi2_independence",
        "variables": [label_a, label_b],
        "n": int(table.sum()),
        "chi2": round(float(chi2), 4),
        "dof": int(dof),
        "p_value": round(float(p), 8),
        "cramers_v": round(cramers_v(table), 4),
        "effect_magnitude": _effect_label(cramers_v(table), len(ra), len(ca)),
        "cells_below_expected_5": round(sparse, 3),
        "note": ("expected counts below 5 in %.0f%% of cells; interpret with care"
                 % (sparse * 100)) if sparse > 0.2 else "expected counts adequate",
    }


def _effect_label(v: float, r: int, c: int) -> str:
    k = min(r, c) - 1
    if k <= 0:
        return "n/a"
    small, medium, large = 0.1, 0.3, 0.5
    if v < small:
        return "negligible"
    if v < medium:
        return "small"
    if v < large:
        return "medium"
    return "large"


def mcnemar(b: int, c: int) -> dict:
    """Paired binary comparison. b/c are discordant pair counts."""
    if b + c == 0:
        return {"test": "mcnemar", "p_value": 1.0}
    res = sps.binomtest(min(b, c), b + c, 0.5)
    return {"test": "mcnemar_exact", "b": b, "c": c,
            "p_value": round(float(res.pvalue), 6)}


# --------------------------------------------------------------------------- #
# Association of a binary outcome with a categorical variable
# --------------------------------------------------------------------------- #
def spearman_trend(xs: Sequence[float], ys: Sequence[float]) -> dict:
    """Monotonic trend across ordered levels (e.g. complexity tiers)."""
    if len(xs) < 3 or len(set(ys)) < 2:
        return {"rho": None, "p_value": None, "n": len(xs)}
    rho, p = sps.spearmanr(xs, ys)
    return {"rho": round(float(rho), 4), "p_value": round(float(p), 6),
            "n": len(xs), "direction": "increasing" if rho > 0 else "decreasing"}


def response_rates(groups: dict[str, tuple[int, int]]) -> list[dict]:
    """groups: {name: (successes, total)} -> rows with Wilson CIs."""
    out = []
    for name, (k, n) in groups.items():
        out.append(proportion_row(k, n, name))
    out.sort(key=lambda r: r["proportion"], reverse=True)
    return out


def lift(base_rate: float, group_rate: float) -> float:
    if base_rate <= 0:
        return 0.0
    return round(group_rate / base_rate, 3)


# --------------------------------------------------------------------------- #
# Reliability
# --------------------------------------------------------------------------- #
def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> dict:
    """Cohen's kappa for two coders on nominal categories."""
    if len(a) != len(b):
        raise ValueError("label vectors differ in length")
    n = len(a)
    if n == 0:
        return {"kappa": None, "n": 0}
    cats = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    return {"kappa": round(kappa, 4), "observed_agreement": round(po, 4),
            "expected_agreement": round(pe, 4), "n": n,
            "interpretation": _kappa_label(kappa)}


def _kappa_label(k: float) -> str:
    if k < 0:
        return "poor"
    if k < 0.21:
        return "slight"
    if k < 0.41:
        return "fair"
    if k < 0.61:
        return "moderate"
    if k < 0.81:
        return "substantial"
    return "almost_perfect"


def macro_f1(gold: Sequence[str], pred: Sequence[str]) -> dict:
    cats = sorted(set(gold) | set(pred))
    f1s, rows = [], []
    correct = sum(1 for g, p in zip(gold, pred) if g == p)
    for c in cats:
        tp = sum(1 for g, p in zip(gold, pred) if g == c and p == c)
        fp = sum(1 for g, p in zip(gold, pred) if g != c and p == c)
        fn = sum(1 for g, p in zip(gold, pred) if g == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f1)
        rows.append({"class": c, "tp": tp, "fp": fp, "fn": fn,
                     "precision": round(prec, 3), "recall": round(rec, 3),
                     "f1": round(f1, 3),
                     "support": sum(1 for g in gold if g == c)})
    return {
        "n": len(gold),
        "accuracy": round(correct / len(gold), 4) if gold else 0.0,
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_class": rows,
    }


def confusion_matrix(gold: Sequence[str], pred: Sequence[str]) -> dict:
    cats = sorted(set(gold) | set(pred))
    idx = {c: i for i, c in enumerate(cats)}
    m = [[0] * len(cats) for _ in cats]
    for g, p in zip(gold, pred):
        m[idx[g]][idx[p]] += 1
    return {"labels": cats, "matrix": m}


def bh_fdr(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Benjamini-Hochberg. The study runs many association tests, so an
    uncorrected p-value would overstate the evidence."""
    items = [(k, v) for k, v in pvalues.items() if v is not None]
    m = len(items)
    items.sort(key=lambda kv: kv[1])
    out: dict[str, dict] = {}
    prev = 1.0
    for rank, (k, p) in reversed(list(enumerate(items, start=1))):
        crit = p * m / rank
        prev = min(prev, crit)
        out[k] = {"p_value": p, "rank": rank,
                  "bh_critical": round(min(1.0, crit), 6),
                  "significant_bh": bool(p <= alpha * rank / m)}
    return out

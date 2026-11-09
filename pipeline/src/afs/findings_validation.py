"""Validation of the *findings*, as distinct from validation of the instrument.

``validation.py`` asks whether the labeller is reliable: does it agree with a
reference annotation, does a label survive harmless perturbations, does
confidence mean anything. That is necessary but not sufficient. The supervisor's
review distinguishes the two and marks "validate the findings" as the remaining
gap, so this module tests the *claims* instead:

F1  Resampling stability   - would the headline rankings survive a different
                             draw from the same population?
F2  Temporal holdout       - do the conclusions hold on records the early corpus
                             could not have contained?
F3  Leave-one-framework-out- is a conclusion an artefact of one repository?
F4  Label-noise sensitivity- how much does a conclusion depend on the labels
                             being right, at the error rate we actually measured?

Each experiment reports the claim it tests, the decision rule, and a plain
verdict: ``stable``, ``direction stable, magnitude uncertain`` or ``not stable``.
Reporting a "not stable" verdict is the point; a validation suite that can only
produce reassurance is not a validation suite.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

import numpy as np

from . import stats
from .common import TAB_DIR, read_json, write_csv, write_json, utc_now
from .taxonomy import Taxonomy

T = Taxonomy()
CATS = T.codes("A_failure_type")

# Frameworks with too few records cannot support a per-framework claim; the
# threshold mirrors the report's own minimum cell rule.
MIN_FRAMEWORK_N = 40


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _observed(records: list[dict]) -> tuple[str, list[str]]:
    counts = Counter(r["A_failure_type"] for r in records)
    ranked = [c for c, _ in counts.most_common()]
    return (ranked[0] if ranked else ""), ranked


def _top3(rank: list[str]) -> set[str]:
    return set(rank[:3])


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 1.0


def _share(records: list[dict], cat: str) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r["A_failure_type"] == cat) / len(records)


# --------------------------------------------------------------------------- #
# F1: resampling stability
# --------------------------------------------------------------------------- #
def bootstrap(records: list[dict], iterations: int = 1000, seed: int = 20261105) -> dict:
    """Non-parametric bootstrap over records.

    Each replicate resamples the corpus with replacement and recomputes the
    category ranking. The reported retention rate is the share of replicates
    that reproduce the observed top category; that number, not the point
    estimate, is what a reader should use to judge how firmly the ordering is
    established.
    """
    rng = np.random.default_rng(seed)
    codes = np.array([CATS.index(r["A_failure_type"]) for r in records])
    n = len(codes)

    obs_top, obs_rank = _observed(records)
    obs_top3 = _top3(obs_rank)
    obs_shares = {c: _share(records, c) for c in CATS}

    top1_hits = 0
    top3_scores: list[float] = []
    per_cat: dict[str, list[float]] = {c: [] for c in CATS}
    top1_counts: Counter = Counter()

    for _ in range(iterations):
        sample = codes[rng.integers(0, n, n)]
        counts = np.bincount(sample, minlength=len(CATS))
        order = np.argsort(-counts)
        rank = [CATS[i] for i in order]
        if rank[0] == obs_top:
            top1_hits += 1
        top1_counts[rank[0]] += 1
        top3_scores.append(_jaccard(_top3(rank), obs_top3))
        for i, c in enumerate(CATS):
            per_cat[c].append(counts[i] / n)

    ci = {}
    for c in CATS:
        arr = np.array(per_cat[c])
        ci[c] = {
            "observed": round(obs_shares[c], 4),
            "boot_mean": round(float(arr.mean()), 4),
            "ci_low": round(float(np.percentile(arr, 2.5)), 4),
            "ci_high": round(float(np.percentile(arr, 97.5)), 4),
        }

    top1_retention = top1_hits / iterations
    top3_stability = float(np.mean(top3_scores))

    if top1_retention >= 0.9:
        verdict = "stable"
    elif top1_retention >= 0.7:
        verdict = "direction stable, magnitude uncertain"
    else:
        verdict = "not stable"

    result = {
        "experiment": "F1_resampling_stability",
        "claim_tested": ("the observed frequency ranking of failure types is a "
                         "property of the population, not of this particular draw"),
        "iterations": iterations,
        "n": n,
        "observed_top": obs_top,
        "observed_top_label": T.label("A_failure_type", obs_top),
        "top1_retention": round(top1_retention, 4),
        "top3_set_stability": round(top3_stability, 4),
        "top1_distribution": {T.label("A_failure_type", k): round(v / iterations, 3)
                              for k, v in top1_counts.most_common()},
        "per_category_ci": ci,
        "verdict": verdict,
        "seed": seed,
        "ran_at": utc_now(),
    }
    write_csv(TAB_DIR / "bootstrap_type_shares.csv", [
        {"category": c, "label": T.label("A_failure_type", c),
         "observed_share": ci[c]["observed"], "ci_low": ci[c]["ci_low"],
         "ci_high": ci[c]["ci_high"]} for c in CATS
    ])
    return result


# --------------------------------------------------------------------------- #
# F2: temporal holdout
# --------------------------------------------------------------------------- #
def temporal_holdout(records: list[dict], split_year: int = 2025) -> dict:
    """Re-derive the composition on later records only.

    The instrument was developed on the whole corpus, so this is not a clean
    out-of-sample test of the *labeller*; it is a test of whether the
    *composition claim* survives the corpus growing. A framework that only
    broke during its own beta period should not drive a general conclusion.
    """
    early = [r for r in records if (r.get("year") or 0) < split_year]
    late = [r for r in records if (r.get("year") or 0) >= split_year]
    if not early or not late:
        return {"experiment": "F2_temporal_holdout", "status": "insufficient_data",
                "n_early": len(early), "n_late": len(late)}

    _, rank_e = _observed(early)
    _, rank_l = _observed(late)
    assoc = stats.chi2_association(
        [r["A_failure_type"] for r in early + late],
        ["early" if (r.get("year") or 0) < split_year else "late" for r in early + late],
        "failure_type", "period")

    top3_overlap = _jaccard(_top3(rank_e), _top3(rank_l))
    same_top = rank_e[0] == rank_l[0]
    shift = []
    for c in CATS:
        a, b = _share(early, c), _share(late, c)
        shift.append({
            "category": c, "label": T.label("A_failure_type", c),
            "early_share": round(a, 4), "late_share": round(b, 4),
            "change_pp": round((b - a) * 100, 2),
        })
    shift.sort(key=lambda d: -abs(d["change_pp"]))

    if same_top and top3_overlap == 1.0:
        verdict = "stable"
    elif same_top or top3_overlap >= 0.5:
        verdict = "direction stable, magnitude uncertain"
    else:
        verdict = "not stable"

    result = {
        "experiment": "F2_temporal_holdout",
        "claim_tested": ("the failure composition is a stable property of these "
                         "frameworks rather than an artefact of their early "
                         "release period"),
        "split_year": split_year,
        "n_early": len(early), "n_late": len(late),
        "early_top": rank_e[0] if rank_e else "",
        "late_top": rank_l[0] if rank_l else "",
        "early_top3": rank_e[:3],
        "late_top3": rank_l[:3],
        "same_top": same_top,
        "top3_overlap": round(top3_overlap, 4),
        "homogeneity": assoc,
        "composition_shift": shift[:6],
        "verdict": verdict,
        "ran_at": utc_now(),
    }
    return result


# --------------------------------------------------------------------------- #
# F3: leave-one-framework-out
# --------------------------------------------------------------------------- #
def leave_one_framework_out(records: list[dict]) -> dict:
    """Drop each framework in turn and re-derive the headline ranking.

    If the ranking is unchanged for every exclusion, no single repository is
    carrying the result. The spread of Cramer's V across exclusions is reported
    alongside, so a conclusion that depends on one framework is visible as a
    large range rather than hidden in an average.
    """
    frameworks = sorted({r["framework"] for r in records})
    obs_top, obs_rank = _observed(records)
    obs_top3 = _top3(obs_rank)

    rows = []
    for fw in frameworks:
        rest = [r for r in records if r["framework"] != fw]
        if len(rest) < 100:
            continue
        top, rank = _observed(rest)
        assoc4 = stats.chi2_association(
            [r["A_failure_type"] for r in rest],
            [r["framework"] for r in rest], "failure_type", "framework")
        rows.append({
            "excluded": fw,
            "n_remaining": len(rest),
            "top_after_exclusion": top,
            "top_label": T.label("A_failure_type", top),
            "top_unchanged": top == obs_top,
            "top3_overlap": round(_jaccard(_top3(rank), obs_top3), 4),
            "cramers_v_framework": assoc4.get("cramers_v"),
            "p_value_framework": assoc4.get("p_value"),
        })

    if not rows:
        return {"experiment": "F3_leave_one_framework_out", "status": "insufficient_data"}

    vs = [r["cramers_v_framework"] for r in rows if r["cramers_v_framework"] is not None]
    unchanged = sum(1 for r in rows if r["top_unchanged"])
    verdict = ("stable" if unchanged == len(rows)
               else "not stable" if unchanged < 0.75 * len(rows)
               else "direction stable, magnitude uncertain")

    result = {
        "experiment": "F3_leave_one_framework_out",
        "claim_tested": ("the headline ranking and the framework association are "
                         "not driven by a single repository"),
        "frameworks_tested": len(rows),
        "top_unchanged_in": unchanged,
        "top_unchanged_share": round(unchanged / len(rows), 4),
        "cramers_v_range": [round(min(vs), 4), round(max(vs), 4)] if vs else [],
        "rows": rows,
        "verdict": verdict,
        "ran_at": utc_now(),
    }
    write_csv(TAB_DIR / "leave_one_framework_out.csv", rows)
    return result


# --------------------------------------------------------------------------- #
# F4: label-noise sensitivity
# --------------------------------------------------------------------------- #
def _confusion_from_gold() -> dict | None:
    """Empirical confusion matrix from the reference annotation, if present."""
    path = TAB_DIR / "validation_gold_eval.json"
    try:
        d = read_json(path)
    except FileNotFoundError:
        return None
    conf = d.get("confusion")
    if not conf:
        return None
    return conf


def label_noise(records: list[dict], simulations: int = 300,
                seed: int = 424242) -> dict:
    """Does the headline ranking survive labels being wrong at the observed rate?

    Two noise models are reported because they bracket the truth:

    * ``symmetric`` - a corrupted label is redrawn from the other categories
      uniformly. This is the pessimistic model: it assumes errors carry no
      structure at all.
    * ``confusion`` - a corrupted label is redrawn from the empirical
      confusion matrix in the reference annotation. This concentrates errors on
      the boundaries the codebook already flags, which is what real coding
      errors look like.

    The corruption rate is the measured disagreement rate, not a guess, so the
    result is conditional on the validation experiment that produced it.
    """
    gold = None
    try:
        g = read_json(TAB_DIR / "validation_gold_eval.json")
        if g.get("status") == "complete":
            gold = g
    except FileNotFoundError:
        gold = None

    error_rate = float(1.0 - gold["accuracy"]) if gold else 0.25
    conf = (gold or {}).get("confusion") or {}

    rng = random.Random(seed)
    obs_top, obs_rank = _observed(records)
    obs_top3 = _top3(obs_rank)
    labels = [r["A_failure_type"] for r in records]

    def corrupt_symmetric(lab: str) -> str:
        others = [c for c in CATS if c != lab]
        return rng.choice(others)

    def corrupt_confusion(lab: str) -> str:
        row = conf.get(lab) or {}
        alts = [(c, w) for c, w in row.items() if c != lab and w > 0]
        if not alts:
            return corrupt_symmetric(lab)
        total = sum(w for _, w in alts)
        x = rng.random() * total
        acc = 0.0
        for c, w in alts:
            acc += w
            if x <= acc:
                return c
        return alts[-1][0]

    def run(model) -> dict:
        top1 = 0
        t3: list[float] = []
        for _ in range(simulations):
            noisy = [model(l) if rng.random() < error_rate else l for l in labels]
            c = Counter(noisy)
            rank = [k for k, _ in c.most_common()]
            if rank[0] == obs_top:
                top1 += 1
            t3.append(_jaccard(_top3(rank), obs_top3))
        return {"top1_retention": round(top1 / simulations, 4),
                "top3_set_stability": round(float(np.mean(t3)), 4)}

    sym = run(corrupt_symmetric)
    cfm = run(corrupt_confusion)

    def verdict(d: dict) -> str:
        # A ranking can survive (top category unchanged) while the *set* of
        # leading categories does not. That distinction matters: it means the
        # ordering is trustworthy but a "top three" claim is not.
        if d["top1_retention"] >= 0.9 and d["top3_set_stability"] >= 0.95:
            return "stable"
        if d["top1_retention"] >= 0.7:
            return "direction stable, magnitude uncertain"
        return "not stable"

    sym_v, cfm_v = verdict(sym), verdict(cfm)
    order = {"stable": 2, "direction stable, magnitude uncertain": 1,
             "not stable": 0}
    result = {
        "experiment": "F4_label_noise_sensitivity",
        "claim_tested": ("the headline ranking does not depend on the labels "
                         "being correct more often than they demonstrably are"),
        "error_rate_source": ("measured disagreement with reference annotation"
                              if gold else "assumed 0.25 (no gold annotation)"),
        "error_rate": round(error_rate, 4),
        "gold_n": (gold or {}).get("n"),
        "simulations": simulations,
        "symmetric": {**sym, "verdict": sym_v},
        "confusion_driven": {**cfm, "verdict": cfm_v},
        # Headline verdict is the weaker of the two noise models, so the
        # summary cannot claim more than either simulation supports.
        "verdict": cfm_v if order[cfm_v] <= order[sym_v] else sym_v,
        "seed": seed,
        "ran_at": utc_now(),
    }
    return result


# --------------------------------------------------------------------------- #
def run_all(records: list[dict]) -> dict:
    out = {
        "generated_at": utc_now(),
        "n_records": len(records),
        "F1_resampling": bootstrap(records),
        "F2_temporal": temporal_holdout(records),
        "F3_leave_one_out": leave_one_framework_out(records),
        "F4_label_noise": label_noise(records),
    }
    verdicts = [out[k]["verdict"] for k in
                ("F1_resampling", "F2_temporal", "F3_leave_one_out")]
    verdicts += [out["F4_label_noise"]["symmetric"]["verdict"],
                 out["F4_label_noise"]["confusion_driven"]["verdict"]]
    out["summary"] = {
        "claims_tested": len(verdicts),
        "stable": sum(1 for v in verdicts if v == "stable"),
        "direction_stable": sum(1 for v in verdicts if v.startswith("direction")),
        "not_stable": sum(1 for v in verdicts if v == "not stable"),
    }
    write_json(TAB_DIR / "findings_validation.json", out)
    return out

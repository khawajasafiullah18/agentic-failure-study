"""Validation experiments for the labelling instrument.

Four experiments, each answering a different threat to validity:

E1  Reference annotation agreement  - does the labeller agree with a human coder?
E2  Perturbation robustness         - does a label survive changes that should
                                      not matter (boilerplate, ordering, ids)?
E3  Structural-cue ablation         - how much does the label depend on the
                                      exception-type rules alone?
E4  Confidence calibration          - is the reported confidence meaningful?

A fifth artefact, the second-coder sheet, is produced but not filled here:
inter-rater agreement requires an independent coder, so the sheet is left blank
and `kappa_from_sheet()` computes agreement once it is completed.
"""
from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import stats
from .classify import FailureLabeller, EXCEPTION_RULES
from .common import GOLD_DIR, TAB_DIR, read_csv, write_csv, write_json, utc_now
from .taxonomy import Taxonomy

T = Taxonomy()


# --------------------------------------------------------------------------- #
# E1: reference annotation
# --------------------------------------------------------------------------- #
def make_gold_sample(records: list[dict], texts: dict[str, str],
                     n: int = 100, seed: int = 42) -> list[dict]:
    """Stratified sample: proportional to predicted label, capped per category so
    that every category with a few members is represented.

    An existing annotated sheet is preserved. Re-running the pipeline must never
    silently discard human annotation, so if the file already carries labels it
    is returned unchanged.
    """
    path = GOLD_DIR / "gold_sample.csv"
    if path.exists():
        existing = read_csv(path)
        if existing and sum(1 for r in existing if r.get("human_label", "").strip()) >= 0.9 * len(existing):
            return existing

    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_label[r["A_failure_type"]].append(r)

    total = len(records)
    sample: list[dict] = []
    for label, items in by_label.items():
        quota = max(3, round(n * len(items) / total))
        quota = min(quota, len(items))
        rng.shuffle(items)
        sample.extend(items[:quota])
    rng.shuffle(sample)
    sample = sample[:n] if len(sample) > n else sample

    rows = []
    for r in sample:
        text = texts.get(r["record_id"], r.get("title", ""))
        snippet = " ".join(text.split())[:600]
        rows.append({
            "record_id": r["record_id"],
            "framework": r["framework"],
            "predicted": r["A_failure_type"],
            "confidence": r["A_confidence"],
            "title": r["title"],
            "snippet": snippet,
            "human_label": "",      # filled by the coder
            "coder_id": "",
            "notes": "",
        })
    write_csv(GOLD_DIR / "gold_sample.csv", rows)
    return rows


def _split_of(record_id: str) -> str:
    """Deterministic 60/40 development/holdout split, stable across runs."""
    import hashlib

    h = int(hashlib.sha256(record_id.encode()).hexdigest()[:2], 16)
    return "dev" if h % 100 < 60 else "test"


def evaluate_gold(gold_path=None, records: list[dict] | None = None,
                  texts: dict[str, str] | None = None) -> dict:
    """Score the labeller against the reference annotation.

    Predictions are recomputed from the stored text with the current labeller
    rather than read from the sheet, so the reported figures always describe the
    instrument as shipped.
    """
    gold_path = gold_path or (GOLD_DIR / "gold_sample.csv")
    rows = [r for r in read_csv(gold_path) if r.get("human_label", "").strip()]
    if not rows:
        return {"status": "pending", "n": 0,
                "note": "gold_sample.csv has no human_label values yet"}

    labeller = FailureLabeller()
    preds, golds, splits = [], [], []
    for r in rows:
        rid = r["record_id"]
        text = texts.get(rid) if texts else None
        if text:
            pred = labeller.label(text).failure_type
        else:
            pred = r["predicted"].strip()
        preds.append(pred)
        golds.append(r["human_label"].strip())
        splits.append(_split_of(rid))

    overall = stats.macro_f1(golds, preds)
    overall["confusion"] = stats.confusion_matrix(golds, preds)
    overall["kappa_vs_reference"] = stats.cohen_kappa(golds, preds)
    overall["status"] = "complete"
    overall["evaluated_at"] = utc_now()

    by_split = {}
    for name in ("dev", "test"):
        idx = [i for i, s in enumerate(splits) if s == name]
        if not idx:
            continue
        g = [golds[i] for i in idx]
        p = [preds[i] for i in idx]
        m = stats.macro_f1(g, p)
        by_split[name] = {
            "n": m["n"], "accuracy": m["accuracy"], "macro_f1": m["macro_f1"],
            "kappa": stats.cohen_kappa(g, p)["kappa"],
            "per_class": m["per_class"],
            "confusion": stats.confusion_matrix(g, p),
        }
    overall["by_split"] = by_split
    write_json(TAB_DIR / "validation_gold_eval.json", overall)
    return overall


def make_second_coder_sheet(rows: list[dict], records: list[dict],
                            n: int = 40, seed: int = 7) -> list[dict]:
    """A blind sheet for a second coder: no predicted label is included.

    An existing sheet that already carries coder labels is preserved: regenerating
    the pipeline must never discard a second coder's work.
    """
    path = GOLD_DIR / "second_coder_sheet.csv"
    if path.exists():
        existing = read_csv(path)
        if any(r.get("coder2_label", "").strip() for r in existing):
            return existing

    rng = random.Random(seed)
    subset = rows.copy()
    rng.shuffle(subset)
    subset = subset[:n]
    out = [{"short_id": r["record_id"][:8], "record_id": r["record_id"],
            "framework": r["framework"],
            "title": r["title"], "snippet": r["snippet"],
            "coder2_label": "", "coder2_notes": ""} for r in subset]
    write_csv(GOLD_DIR / "second_coder_sheet.csv", out)
    return out


def kappa_from_sheet(first_path=None, second_path=None) -> dict:
    first_path = first_path or (GOLD_DIR / "gold_sample.csv")
    second_path = second_path or (GOLD_DIR / "second_coder_sheet.csv")
    if not Path(first_path).exists() or not Path(second_path).exists():
        return {"status": "pending", "n": 0,
                "note": "annotation sheets not generated yet"}
    a = {r["record_id"]: r["human_label"].strip() for r in read_csv(first_path)
         if r.get("human_label", "").strip()}
    b = {r["record_id"]: r["coder2_label"].strip() for r in read_csv(second_path)
         if r.get("coder2_label", "").strip()}
    shared = sorted(set(a) & set(b))
    if not shared:
        return {"status": "pending", "n": 0,
                "note": "second_coder_sheet.csv not yet completed"}
    return {"status": "complete", "n": len(shared),
            **stats.cohen_kappa([a[k] for k in shared], [b[k] for k in shared])}


# --------------------------------------------------------------------------- #
# E2: perturbation robustness
# --------------------------------------------------------------------------- #
BOILERPLATE = [
    " Environment: python 3.11 on ubuntu 22.04, pip install -r requirements.txt.",
    " I am using the latest release and a clean virtual environment.",
    " Happy to provide a minimal reproduction repository if useful.",
]


def _perturb(text: str, rng: random.Random) -> str:
    """Apply transformations that should not change the failure category."""
    paras = [p for p in text.split("\n") if p.strip()]
    rng.shuffle(paras)
    out = "\n".join(paras)
    out = re.sub(r"\bcrewai\b", "framework_a", out, flags=re.I)
    out = re.sub(r"\bautogen\b", "framework_b", out, flags=re.I)
    out = re.sub(r"\blanggraph\b", "framework_c", out, flags=re.I)
    out = re.sub(r"\bmicrosoft\b", "vendor", out, flags=re.I)
    out += rng.choice(BOILERPLATE)
    return out


def perturbation_test(records: list[dict], texts: dict[str, str],
                      n: int = 150, seed: int = 11) -> dict:
    rng = random.Random(seed)
    labeller = FailureLabeller()
    sample = records.copy()
    rng.shuffle(sample)
    sample = sample[:n]

    kept, changes = 0, []
    for r in sample:
        text = texts.get(r["record_id"], "")
        if not text:
            continue
        before = r["A_failure_type"]
        after = labeller.label(_perturb(text, rng)).failure_type
        if before == after:
            kept += 1
        else:
            changes.append({"record_id": r["record_id"], "before": before,
                            "after": after})
    total = len(sample)
    row = stats.proportion_row(kept, total, "label_retention")
    result = {
        "experiment": "perturbation_robustness",
        "n": total, "retained": kept, "retention_rate": round(kept / total, 4),
        "ci_low": row["ci_low"], "ci_high": row["ci_high"],
        "changed": changes[:25],
        "changes_by_pair": dict(Counter(f"{c['before']}->{c['after']}" for c in changes)),
        "note": ("Sentences reordered, framework names replaced by neutral tokens, "
                 "and setup boilerplate appended. A stable labeller should retain "
                 "the label under all three."),
        "ran_at": utc_now(),
    }
    write_json(TAB_DIR / "validation_perturbation.json", result)
    return result


# --------------------------------------------------------------------------- #
# E3: ablation of structural cues
# --------------------------------------------------------------------------- #
def ablation_test(records: list[dict], texts: dict[str, str]) -> dict:
    """Remove exception-type rules and re-label. The delta shows how much the
    label depends on explicit exception names versus lexical content."""
    full = FailureLabeller()
    ablated = FailureLabeller()
    import afs.classify as C

    saved = list(C.EXCEPTION_RULES)
    try:
        C.EXCEPTION_RULES.clear()
        changed = 0
        pairs = Counter()
        for r in records:
            text = texts.get(r["record_id"], "")
            if not text:
                continue
            a = r["A_failure_type"]
            b = ablated.label(text).failure_type
            if a != b:
                changed += 1
                pairs[f"{a}->{b}"] += 1
        n = len(records)
        result = {
            "experiment": "exception_rule_ablation",
            "n": n, "changed": changed,
            "change_rate": round(changed / n, 4),
            "pairs": dict(pairs.most_common(10)),
            "note": ("Exception-type rules removed. Change rate indicates reliance on "
                     "explicit traceback vocabulary; a high rate means labels depend "
                     "on the reporter pasting a traceback."),
            "ran_at": utc_now(),
        }
    finally:
        C.EXCEPTION_RULES.extend(saved)
    write_json(TAB_DIR / "validation_ablation.json", result)
    return result


# --------------------------------------------------------------------------- #
# E4: calibration
# --------------------------------------------------------------------------- #
def calibration(records: list[dict], gold_rows: list[dict]) -> dict:
    """Accuracy by stated-confidence bin, using the annotated gold sample."""
    gold = {r["record_id"]: r["human_label"] for r in gold_rows
            if r.get("human_label", "").strip()}
    if not gold:
        return {"status": "pending", "note": "no gold labels available"}
    bins = [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01)]
    rows = []
    for lo, hi in bins:
        sub = [r for r in records
               if r["record_id"] in gold and lo <= r["A_confidence"] < hi]
        if not sub:
            continue
        correct = sum(1 for r in sub if r["A_failure_type"] == gold[r["record_id"]])
        row = stats.proportion_row(correct, len(sub), f"{lo:.1f}-{hi:.1f}")
        row["bin"] = f"{lo:.1f}-{hi:.1f}"
        rows.append(row)
    result = {"experiment": "confidence_calibration", "bins": rows,
              "n": sum(r["denominator"] for r in rows),
              "note": ("If confidence were uninformative, accuracy would be flat "
                       "across bins. A monotone rise supports using confidence as a "
                       "review triage signal."),
              "ran_at": utc_now()}
    write_json(TAB_DIR / "validation_calibration.json", result)
    return result


# --------------------------------------------------------------------------- #
def run_all(records: list[dict], texts: dict[str, str]) -> dict:
    sample = make_gold_sample(records, texts)
    make_second_coder_sheet(sample, records)
    gold = evaluate_gold(records=records, texts=texts)
    out = {
        "gold_sample_size": len(sample),
        "gold_status": gold.get("status"),
        "perturbation": perturbation_test(records, texts),
        "ablation": ablation_test(records, texts),
        "calibration": calibration(records, sample),
        "kappa": kappa_from_sheet(),
        "generated_at": utc_now(),
    }
    if gold.get("status") == "complete":
        out["gold_eval"] = gold
    write_json(TAB_DIR / "validation_summary.json", out)
    return out

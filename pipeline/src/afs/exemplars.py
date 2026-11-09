"""Traceable exemplars: a worked, citable example for every taxonomy category.

The supervisor's conformance checklist asks for "real examples for each failure
type ... traceable examples from real datasets/logs for each taxonomy
category". The corpus already stores a source URL and an evidence span for
every record, but a reader should not have to query a 3,089-row file to find
one. This module selects a small, defensible exemplar set per category and
writes it out as both a table and prose that the report can embed.

Selection rule (stated so the choice is auditable and not cherry-picked)
-----------------------------------------------------------------------
A "good" exemplar is one where the *text* demonstrates the definition, not one
where the labeller happened to be confident. Confidence is a function of the
same rules that produced the label, so ranking on confidence alone rewards
records with a single loud token (typically a pasted traceback) and can surface
a borderline case as if it were canonical. Exemplars are therefore ranked on a
demonstration score:

    q = (top category score - best competing score)          separation
        + 1.5 * (category pattern matched in the title)      reporter's words
        - 2.0 * (label came from a fallback heuristic)       derived, not direct
        - 1.0 * (evidence span shorter than 80 characters)   nothing to check

Only records above a decisive-evidence threshold are eligible. Ties break on
record id, so the same exemplars are produced on every run, and at most two
examples are taken from a single framework so a category is shown across
projects.

Every exemplar keeps its record id, repository, issue number, URL and evidence
span. A reader can open the URL and check the claim without access to this
codebase.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .classify import FailureLabeller
from .common import TAB_DIR, write_csv, utc_now
from .taxonomy import Taxonomy

T = Taxonomy()

DECISIVE = 2.6            # minimum score for a category to be demonstrated
MIN_Q = 2.0               # minimum demonstration score to be shown as an exemplar
FALLBACK_RULES = ("HEUR:bare-traceback", "R4:residual-functionality",
                  "R4:below-threshold")
RESIDUAL_SIGNAL = re.compile(
    r"\b(error|errors|exception|fail(s|ed|ure)?|crash(es|ed)?|bug|broken|"
    r"invalid|wrong|doesn'?t work|not work)\b", re.I)


# Trim an evidence span to whole words so the excerpt never ends mid-token.
def _trim(text: str, limit: int = 260) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + " ..."


def _quality(lab, title: str, labeller) -> tuple[float, dict]:
    """Demonstration score for one labelled record.

    Positive terms reward a label that the text supports unambiguously and that
    the title alone also yields. Negative terms penalise a label that was
    reached by a fallback rule or that has no span a reader could inspect.
    """
    scores = lab.type_scores or {}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0][1] if ranked else 0.0
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    sep = top - second

    # Read the title in isolation: if a reporter's one-line summary lands in the
    # same category, the example needs no traceback to make its point.
    title_agree = 1.0 if (title and
                          labeller.label(title).failure_type == lab.failure_type) else 0.0

    fallback = any(r in lab.matched_rules for r in FALLBACK_RULES)
    short_span = 1.0 if len(lab.evidence_span.strip()) < 80 else 0.0

    q = sep + 1.5 * title_agree - 2.0 * float(fallback) - 1.0 * short_span
    return q, {"top": top, "sep": sep, "title_hit": title_agree,
               "fallback": fallback, "short_span": short_span}


def select(records: list[dict], texts: dict[str, str], per_category: int = 5,
           max_per_framework: int = 2, pool: int = 60) -> list[dict]:
    """Pick a framework-diverse, demonstrably-supported exemplar set per category."""
    labeller = FailureLabeller()
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["A_failure_type"]].append(r)

    rows: list[dict] = []
    for cat in T.codes("A_failure_type"):
        # Cheap pre-filter: the pool only needs the records most likely to pass
        # the decisive-evidence test, so full labels are recomputed for a few
        # dozen candidates per category rather than the whole corpus.
        candidates = sorted(
            by_cat.get(cat, []),
            key=lambda r: (-float(r.get("A_confidence") or 0), r["record_id"]),
        )[:pool]

        scored: list[tuple[float, dict]] = []
        for r in candidates:
            text = texts.get(r["record_id"], "")
            if not text:
                continue
            lab = labeller.label(text)
            if lab.failure_type != cat:
                continue            # label drifted; not a demonstration of `cat`
            # A reader must be able to see the text that justifies the label.
            span = (lab.evidence_span or r.get("A_evidence") or "").strip()
            is_residual = cat == "A10_unknown"
            if is_residual:
                # The residual category carries no evidence span by design, so
                # the reporter's own opening passage is quoted instead. Records
                # rejected as proposals or documentation are not failures at all
                # and would misrepresent what the category means.
                if any("PRE:proposal-or-doc" in x for x in lab.matched_rules):
                    continue
                if not RESIDUAL_SIGNAL.search(text):
                    continue
                span = span or " ".join(text.split())[:400]
            if len(span) < 40:
                continue
            q, detail = _quality(lab, r.get("title", ""), labeller)
            if detail["top"] < DECISIVE and not is_residual:
                continue            # too weak to stand for the category
            if q < MIN_Q and not is_residual:
                continue            # not a clear demonstration of the definition
            scored.append((q, {**r, "_q": q, "_detail": detail, "_lab": lab,
                               "_span": span}))

        scored.sort(key=lambda t: (-t[0], t[1]["record_id"]))

        picked: list[dict] = []
        used_fw: dict[str, int] = defaultdict(int)
        for pass_no in (1, 2):
            for _q, r in scored:
                if len(picked) >= per_category or any(p["record_id"] == r["record_id"]
                                                      for p in picked):
                    continue
                if pass_no == 1 and used_fw[r["framework"]] >= max_per_framework:
                    continue
                picked.append(r)
                used_fw[r["framework"]] += 1
            if len(picked) >= per_category:
                break

        meta = T.categories("A_failure_type")[cat]
        for i, r in enumerate(picked, start=1):
            lab = r["_lab"]
            rows.append({
                "category": cat,
                "category_label": meta.get("label", cat),
                "definition": " ".join(str(meta.get("definition", "")).split()),
                "rank_in_category": i,
                "record_id": r["record_id"],
                "framework": r["framework"],
                "repo": r.get("repo", ""),
                "issue_number": r.get("issue_number", ""),
                "url": r.get("url", ""),
                "created_at": r.get("created_at", ""),
                "confidence": r.get("A_confidence", ""),
                "demonstration_score": round(r["_q"], 2),
                "category_score": round(r["_detail"]["top"], 2),
                "score_separation": round(r["_detail"]["sep"], 2),
                "cause_class": r.get("B_cause_class", ""),
                "severity": r.get("D_severity", ""),
                "detection_point": r.get("E_detection_point", ""),
                "title": r.get("title", ""),
                "evidence": _trim(r["_span"]),
            })
    return rows


def coverage(records: list[dict]) -> list[dict]:
    """Per-category counts, so a reader sees the support behind each exemplar."""
    counts: dict[str, int] = defaultdict(int)
    frameworks: dict[str, set] = defaultdict(set)
    confs: dict[str, list[float]] = defaultdict(list)
    for r in records:
        c = r["A_failure_type"]
        counts[c] += 1
        frameworks[c].add(r["framework"])
        confs[c].append(float(r.get("A_confidence") or 0))

    out = []
    for cat in T.codes("A_failure_type"):
        fw = sorted(frameworks.get(cat, []))
        cs = confs.get(cat, [])
        out.append({
            "category": cat,
            "category_label": T.label("A_failure_type", cat),
            "records": counts.get(cat, 0),
            "frameworks_represented": len(fw),
            "framework_list": "; ".join(fw),
            "mean_confidence": round(sum(cs) / len(cs), 3) if cs else "",
        })
    return out


def build(records: list[dict], texts: dict[str, str] | None = None,
          per_category: int = 5) -> dict:
    texts = texts or {}
    rows = select(records, texts, per_category=per_category)
    cov = coverage(records)
    write_csv(TAB_DIR / "taxonomy_exemplars.csv", rows)
    write_csv(TAB_DIR / "taxonomy_exemplar_coverage.csv", cov)

    empty = [c["category_label"] for c in cov if not c["records"]]
    thin = [c["category_label"] for c in cov if 0 < c["records"] < per_category]
    missing = sorted({c for c in T.codes("A_failure_type")
                      if c not in {r["category"] for r in rows}})
    return {
        "exemplars": len(rows),
        "categories": len(cov),
        "categories_without_examples": empty,
        "categories_unable_to_reach_target": missing,
        "categories_with_fewer_than_target": thin,
        "per_category": per_category,
        "generated_at": utc_now(),
    }

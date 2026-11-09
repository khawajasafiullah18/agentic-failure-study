"""Analysis functions: one per research question.

Each function takes the record list and returns a dict with three keys:

    table   - rows ready for CSV / markdown rendering
    metrics - the headline numbers, used by the critic for verification
    note    - a sentence stating method and limitation

Nothing in this module formats text for humans; that is the reporter's job. This
separation is what lets the critic recompute a number independently of how it
was presented.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import stats
from .common import PROC_DIR, TAB_DIR, read_jsonl, write_csv
from .taxonomy import Taxonomy

T = Taxonomy()


# --------------------------------------------------------------------------- #
def load_records() -> list[dict]:
    from .complexity import enrich

    records = read_jsonl(PROC_DIR / "failures.jsonl")
    texts = {r["record_id"]: r["text"] for r in read_jsonl(PROC_DIR / "texts.jsonl")}
    return enrich(records, texts)


def _label(code: str) -> str:
    return T.label("A_failure_type", code)


def _cause_label(code: str) -> str:
    return T.label("B_cause_class", code)


# --------------------------------------------------------------------------- #
# RQ1 / RQ2: distribution and ranking
# --------------------------------------------------------------------------- #
def rq1_frequency(records: list[dict]) -> dict:
    n = len(records)
    counts = Counter(r["A_failure_type"] for r in records)
    rows = []
    for code, k in counts.most_common():
        row = stats.proportion_row(k, n, _label(code))
        row["code"] = code
        rows.append(row)
    return {
        "table": rows,
        "metrics": {"n_records": n, "n_categories": len(counts),
                    "top_category": rows[0]["code"] if rows else None,
                    "top_share": rows[0]["proportion"] if rows else 0.0},
        "note": (f"Frequency of failure type over {n} retained records; "
                 "Wilson 95% intervals; denominator includes unknown labels."),
    }


def rq2_ranked(records: list[dict]) -> dict:
    n = len(records)
    counts = Counter(r["A_failure_type"] for r in records)
    rows = []
    for code, k in counts.most_common():
        row = stats.proportion_row(k, n, _label(code))
        row["code"] = code
        hi = [r for r in records
              if r["A_failure_type"] == code and r["A_confidence"] >= 0.6]
        row["high_confidence_count"] = len(hi)
        row["share_when_confident"] = round(len(hi) / max(k, 1), 3)
        rows.append(row)
    # sensitivity: recompute shares using high-confidence labels only
    conf = [r for r in records if r["A_confidence"] >= 0.6]
    sens = []
    if conf:
        cc = Counter(r["A_failure_type"] for r in conf)
        for code, k in cc.most_common():
            sens.append({"code": code, "label": _label(code),
                         "share_of_confident": round(k / len(conf), 4)})
    return {
        "table": rows,
        "sensitivity": sens,
        "metrics": {"n_records": n, "n_confident": len(conf),
                    "top_category": rows[0]["code"] if rows else None,
                    "top_share": rows[0]["proportion"] if rows else 0.0,
                    "top_share_confident": sens[0]["share_of_confident"] if sens else 0.0},
        "note": ("Ranking with intervals, plus a sensitivity analysis restricted "
                 "to labels with confidence >= 0.60."),
    }


# --------------------------------------------------------------------------- #
# RQ3: causes associated with types
# --------------------------------------------------------------------------- #
def rq3_cause_by_type(records: list[dict]) -> dict:
    types = [c for c in T.codes("A_failure_type")
             if c != "A10_unknown" and any(r["A_failure_type"] == c for r in records)]
    causes = [c for c in T.codes("B_cause_class")
              if any(r["B_cause_class"] == c for r in records)]

    counts = Counter((r["A_failure_type"], r["B_cause_class"]) for r in records)
    row_totals = Counter(r["A_failure_type"] for r in records)

    matrix, rows = [], []
    for t in types:
        line = []
        for c in causes:
            k = counts[(t, c)]
            share = round(100 * k / row_totals[t], 1) if row_totals[t] else 0.0
            line.append(share)
            if k:
                rows.append({
                    "failure_type": t, "failure_type_label": _label(t),
                    "cause": c, "cause_label": _cause_label(c),
                    "count": k, "type_total": row_totals[t],
                    "share_of_type_pct": share,
                })
        matrix.append(line)
    rows.sort(key=lambda r: r["share_of_type_pct"], reverse=True)

    test = stats.chi2_association(
        [r["A_failure_type"] for r in records],
        [r["B_cause_class"] for r in records],
        "failure_type", "cause_class")
    test["p_value"] = test.get("p_value")

    # evidence grading matters: how many causes are demonstrable?
    grades = Counter(r["B_evidence_grade"] for r in records)
    return {
        "table": rows,
        "matrix": {"rows": types, "cols": causes, "values": matrix},
        "metrics": {"n_records": len(records),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v"),
                    "dof": test.get("dof"),
                    "demonstrated_causes": grades.get("demonstrated", 0),
                    "grade_counts": dict(grades)},
        "association": test,
        "note": ("Cause (dimension B) crossed with failure type (dimension A). "
                 "Chi-square with Cramer's V; BH correction applied across all "
                 "association tests in the study. Association is not causation."),
    }


# --------------------------------------------------------------------------- #
# RQ4: framework composition
# --------------------------------------------------------------------------- #
def rq4_framework_by_type(records: list[dict]) -> dict:
    fws = sorted({r["framework"] for r in records})
    types = [c for c in T.codes("A_failure_type")
             if any(r["A_failure_type"] == c for r in records)]
    counts = Counter((r["framework"], r["A_failure_type"]) for r in records)
    totals = Counter(r["framework"] for r in records)

    series = {}
    for fw in fws:
        series[fw] = [round(100 * counts[(fw, t)] / totals[fw], 1) for t in types]

    rows = []
    for fw in fws:
        for t in types:
            k = counts[(fw, t)]
            if k:
                rows.append({"framework": fw, "failure_type": t,
                             "failure_type_label": _label(t), "count": k,
                             "framework_total": totals[fw],
                             "share_pct": round(100 * k / totals[fw], 1)})

    test = stats.chi2_association(
        [r["framework"] for r in records],
        [r["A_failure_type"] for r in records],
        "framework", "failure_type")

    # most distinctive type per framework vs pooled baseline
    baseline = Counter(r["A_failure_type"] for r in records)
    n = len(records)
    distinctive = []
    for fw in fws:
        best = None
        for t in types:
            base = baseline[t] / n if n else 0
            rate = counts[(fw, t)] / totals[fw] if totals[fw] else 0
            lf = stats.lift(base, rate)
            if best is None or lf > best["lift"]:
                best = {"framework": fw, "failure_type": t,
                        "lift": lf, "framework_rate": round(rate, 4),
                        "baseline_rate": round(base, 4)}
        if best:
            distinctive.append(best)
    return {
        "table": rows,
        "series": series,
        "types": types,
        "totals": dict(totals),
        "distinctive": distinctive,
        "metrics": {"n_records": n, "n_frameworks": len(fws),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v")},
        "association": test,
        "note": ("Framework composition compared. Lift = framework rate / pooled "
                 "rate; a lift above 1 means the type is over-represented."),
    }


# --------------------------------------------------------------------------- #
# RQ5: severity by framework
# --------------------------------------------------------------------------- #
def rq5_framework_severity(records: list[dict]) -> dict:
    fws = sorted({r["framework"] for r in records})
    groups = {}
    rows = []
    for fw in fws:
        sub = [r for r in records if r["framework"] == fw]
        k = sum(1 for r in sub if r["D_severity"] == "D1_blocking")
        groups[fw] = (k, len(sub))
        row = stats.proportion_row(k, len(sub), fw)
        row["framework"] = fw
        rows.append(row)
    rows.sort(key=lambda r: r["proportion"], reverse=True)

    pairwise = []
    for i in range(len(fws)):
        for j in range(i + 1, len(fws)):
            a, b = fws[i], fws[j]
            k1, n1 = groups[a]
            k2, n2 = groups[b]
            if n1 and n2:
                res = stats.two_proportion_test(k1, n1, k2, n2)
                pairwise.append({"pair": f"{a} vs {b}", **res})

    tested = {p["pair"]: p["p_value"] for p in pairwise}
    corr = stats.bh_fdr(tested)
    for p in pairwise:
        p["significant_bh"] = corr.get(p["pair"], {}).get("significant_bh")

    return {
        "table": rows,
        "pairwise": pairwise,
        "metrics": {"n_records": len(records),
                    "n_frameworks": len(fws),
                    "max_rate": rows[0]["proportion"] if rows else 0.0,
                    "min_rate": rows[-1]["proportion"] if rows else 0.0},
        "note": ("Blocking-failure rate per framework (severity D1). Fisher exact "
                 "for sparse 2x2 tables; BH correction across pairwise tests."),
    }


# --------------------------------------------------------------------------- #
# RQ6: complexity
# --------------------------------------------------------------------------- #
def rq6_complexity(records: list[dict]) -> dict:
    from .complexity import tier_summary

    rows = tier_summary(records)
    # chi-square across tiers for orchestration/context failure
    rt, ct = [], []
    for r in records:
        rt.append(str(r["complexity_tier"]))
        ct.append("orch_context" if r["A_failure_type"] in
                  ("A4_communication", "A5_context_memory") else "other")
    test = stats.chi2_association(rt, ct, "complexity_tier", "orchestration_or_context")

    trend = None
    if len(rows) >= 3:
        xs = [r["tier"] for r in rows]
        ys = [r["proportion"] for r in rows]
        trend = stats.spearman_trend(xs, ys)

    by_tier_type = []
    for tier in sorted({r["complexity_tier"] for r in records}):
        sub = [r for r in records if r["complexity_tier"] == tier]
        counts = Counter(r["A_failure_type"] for r in sub)
        for t, k in counts.most_common():
            by_tier_type.append({"tier": tier, "failure_type": t,
                                 "failure_type_label": _label(t), "count": k,
                                 "tier_total": len(sub),
                                 "share_pct": round(100 * k / len(sub), 1)})
    return {
        "table": rows,
        "by_tier_type": by_tier_type,
        "metrics": {"n_records": len(records),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v"),
                    "trend": trend},
        "association": test,
        "note": ("Complexity = number of reported capabilities (multi-agent, tools, "
                 "memory/state), 0-3. Textual proxy: capabilities present but not "
                 "described are missed, which biases results towards the null."),
    }


# --------------------------------------------------------------------------- #
# RQ7: escapes
# --------------------------------------------------------------------------- #
def rq7_escape(records: list[dict]) -> dict:
    types = [c for c in T.codes("A_failure_type") if c != "A10_unknown"]
    rows = []
    for t in types:
        sub = [r for r in records if r["A_failure_type"] == t]
        if not sub:
            continue
        escaped = sum(1 for r in sub
                      if r["E_detection_point"] in ("E3_human_observation",
                                                    "E4_production_monitoring"))
        row = stats.proportion_row(escaped, len(sub), _label(t))
        row["code"] = t
        row["runtime_caught"] = len(sub) - escaped
        rows.append(row)
    rows.sort(key=lambda r: r["proportion"], reverse=True)

    det = Counter(r["E_detection_point"] for r in records)
    det_rows = [{"detection_point": k, "count": v,
                 "share_pct": round(100 * v / len(records), 1)}
                for k, v in det.most_common()] if records else []

    test = stats.chi2_association(
        [r["A_failure_type"] for r in records],
        [r["E_detection_point"] for r in records],
        "failure_type", "detection_point")
    return {
        "table": rows,
        "detection_table": det_rows,
        "metrics": {"n_records": len(records),
                    "escape_share": round(sum(r["count"] for r in rows) /
                                          max(len(records), 1), 4),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v")},
        "association": test,
        "note": ("Escape = detected by human observation or monitoring rather than by "
                 "the framework runtime or a test. Framework-reported issues are "
                 "by construction visible; the metric therefore measures relative "
                 "escapement, not absolute field failure rates."),
    }


# --------------------------------------------------------------------------- #
# RQ8: unknown share
# --------------------------------------------------------------------------- #
def rq8_unknown(records: list[dict]) -> dict:
    rows = []
    fws = sorted({r["framework"] for r in records})
    for fw in fws:
        sub = [r for r in records if r["framework"] == fw]
        k = sum(1 for r in sub if r["A_failure_type"] == "A10_unknown")
        row = stats.proportion_row(k, len(sub), fw)
        row["framework"] = fw
        rows.append(row)
    total_unknown = sum(1 for r in records if r["A_failure_type"] == "A10_unknown")
    overall = stats.proportion_row(total_unknown, len(records), "all frameworks")

    test = stats.two_proportion_test(
        total_unknown, len(records),
        len(records) - total_unknown, len(records)) if records else {}

    return {
        "table": rows,
        "overall": overall,
        "metrics": {"n_records": len(records), "unknown": total_unknown,
                    "unknown_share": round(total_unknown / max(len(records), 1), 4),
                    "coverage": round(1 - total_unknown / max(len(records), 1), 4)},
        "note": ("Unclassified share reported explicitly; unknown records stay in "
                 "every denominator so coverage is not overstated."),
    }


# --------------------------------------------------------------------------- #
# RQ9: time trend
# --------------------------------------------------------------------------- #
def rq9_trend(records: list[dict]) -> dict:
    by_year = defaultdict(list)
    for r in records:
        if r.get("year"):
            by_year[r["year"]].append(r)
    years = sorted(y for y in by_year if len(by_year[y]) >= 10)
    rows, series = [], {}
    for y in years:
        sub = by_year[y]
        counts = Counter(r["A_failure_type"] for r in sub)
        props = {t: round(100 * k / len(sub), 1) for t, k in counts.items()}
        rows.append({"year": y, "records": len(sub), "proportions": props})

    # test whether orchestration/context share changes over time
    rt = [str(r["year"]) for r in records if r.get("year") and str(r["year"])]
    ct = ["orch_context" if r["A_failure_type"] in
          ("A4_communication", "A5_context_memory") else "other"
          for r in records if r.get("year")]
    test = stats.chi2_association(rt, ct, "year", "orchestration_or_context")
    return {
        "table": rows,
        "metrics": {"years_analysed": years, "n_records": sum(len(by_year[y]) for y in years),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v")},
        "association": test,
        "note": ("Composition by calendar year; years with fewer than 10 records are "
                 "omitted. Sampling is by issue recency, so early years are "
                 "under-represented by design."),
    }


# --------------------------------------------------------------------------- #
# RQ10: tool / orchestration strata
# --------------------------------------------------------------------------- #
def rq10_strata(records: list[dict]) -> dict:
    rows = []
    for name, pred in [
        ("uses_tools", lambda r: bool(r.get("uses_tools"))),
        ("no_tools", lambda r: not r.get("uses_tools")),
        ("multi_agent", lambda r: bool(r.get("multi_agent"))),
        ("single_agent", lambda r: not r.get("multi_agent")),
        ("uses_memory", lambda r: bool(r.get("uses_memory"))),
    ]:
        sub = [r for r in records if pred(r)]
        if not sub:
            continue
        counts = Counter(r["A_failure_type"] for r in sub)
        for t, k in counts.most_common(4):
            rows.append({"stratum": name, "failure_type": t,
                         "failure_type_label": _label(t), "count": k,
                         "stratum_total": len(sub),
                         "share_pct": round(100 * k / len(sub), 1)})

    tt, tc = [], []
    for r in records:
        tt.append("tools" if r.get("uses_tools") else "no_tools")
        tc.append(r["A_failure_type"])
    test = stats.chi2_association(tt, tc, "uses_tools", "failure_type")
    return {
        "table": rows,
        "metrics": {"n_records": len(records),
                    "chi2": test.get("chi2"), "p_value": test.get("p_value"),
                    "cramers_v": test.get("cramers_v")},
        "association": test,
        "note": ("Stratified composition by declared tool use and orchestration. "
                 "Strata overlap: a record can use tools and be multi-agent."),
    }


ALL_RQ = {
    "RQ1": rq1_frequency,
    "RQ2": rq2_ranked,
    "RQ3": rq3_cause_by_type,
    "RQ4": rq4_framework_by_type,
    "RQ5": rq5_framework_severity,
    "RQ6": rq6_complexity,
    "RQ7": rq7_escape,
    "RQ8": rq8_unknown,
    "RQ9": rq9_trend,
    "RQ10": rq10_strata,
}


def export_tables(results: dict[str, dict]) -> None:
    for rq, res in results.items():
        rows = res.get("table") or []
        if rows:
            write_csv(TAB_DIR / f"{rq.lower()}_table.csv", rows)

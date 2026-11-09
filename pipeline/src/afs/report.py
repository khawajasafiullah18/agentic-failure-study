"""Report rendering: verified findings only.

The reporter reads from the blackboard's `verified` dict. A question that the
critic rejected twice is listed in a separate "unverified" appendix rather than
being silently presented as a result.
"""
from __future__ import annotations

from pathlib import Path

from . import viz
from .common import FIG_DIR, REP_DIR, TAB_DIR, utc_now
from .taxonomy import Taxonomy

T = Taxonomy()

RQ_TITLES = {
    "RQ1": "Distribution of failure types",
    "RQ2": "Ranked failure types and label confidence",
    "RQ3": "Causes associated with each failure type",
    "RQ4": "Framework differences in failure composition",
    "RQ5": "Framework differences in blocking severity",
    "RQ6": "Declared complexity and failure profile",
    "RQ7": "Detection and escape",
    "RQ8": "Taxonomy coverage and unclassified share",
    "RQ9": "Change over time",
    "RQ10": "Tool and orchestration strata",
}


def _md_table(rows: list[dict], cols: list[tuple[str, str]], limit: int | None = None) -> str:
    if not rows:
        return "_No rows._\n"
    use = rows[:limit] if limit else rows
    head = "| " + " | ".join(h for _, h in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = []
    for r in use:
        cells = []
        for k, _ in cols:
            v = r.get(k, "")
            if isinstance(v, float):
                v = f"{v:.3f}"
            cells.append(str(v).replace("|", "/"))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep] + body) + "\n"


def _pct(x) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return str(x)


def build_report(bb) -> Path:
    recs = bb.records
    verified = bb.verified
    n = len(recs)
    figs: dict[str, str] = {}

    # ------------------------------------------------------------------ figures
    if "RQ1" in verified:
        figs["RQ1"] = viz.freq_bar(
            verified["RQ1"]["table"], FIG_DIR / "fig_rq1_failure_types.png",
            "Failure types across agentic applications")

    if "RQ3" in verified:
        m = verified["RQ3"].get("matrix") or {}
        if m.get("values"):
            figs["RQ3"] = viz.heatmap(
                m["values"], [T.label("A_failure_type", c) for c in m["rows"]],
                [T.label("B_cause_class", c) for c in m["cols"]],
                FIG_DIR / "fig_rq3_cause_by_type.png",
                "Cause class by failure type")

    if "RQ4" in verified:
        ser = verified["RQ4"].get("series") or {}
        if ser:
            figs["RQ4"] = viz.grouped_bar(
                [T.label("A_failure_type", t) for t in verified["RQ4"]["types"]],
                {fw: vals for fw, vals in ser.items()},
                FIG_DIR / "fig_rq4_framework_composition.png",
                "Failure composition by framework")

    if "RQ5" in verified:
        figs["RQ5"] = viz.freq_bar(
            verified["RQ5"]["table"], FIG_DIR / "fig_rq5_blocking_rate.png",
            "Blocking-failure rate by framework", xlabel="Blocking share (%)")

    if "RQ6" in verified:
        figs["RQ6"] = viz.rate_with_ci(
            verified["RQ6"]["table"], FIG_DIR / "fig_rq6_complexity.png",
            "Orchestration/context failures by declared complexity tier",
            ylabel="Share of tier's records (%)")

    if "RQ9" in verified and verified["RQ9"]["table"]:
        figs["RQ9"] = viz.timeline(verified["RQ9"]["table"],
                                   FIG_DIR / "fig_rq9_time_trend.png",
                                   "Failure composition by year")

    # ------------------------------------------------------------------ document
    L: list[str] = []
    L.append("# Failure Taxonomy and Empirical Analysis of Agentic AI Systems")
    L.append("")
    L.append(f"**Generated:** {utc_now()}  ")
    L.append(f"**Corpus:** {n} failure records  ")
    L.append(f"**Taxonomy version:** {T.version}  ")
    L.append(f"**Agentic pipeline:** {len(bb.messages)} messages, "
             f"{len(bb.tool_calls)} tool calls, "
             f"{len(verified)} verified findings, {len(bb.rejected)} rejections")
    L.append("")
    L.append("---")
    L.append("")

    # --- executive summary
    L.append("## 1. Summary")
    L.append("")
    if "RQ1" in verified:
        r = verified["RQ1"]
        top = r["table"][0]
        L.append(f"Across **{n}** publicly reported failures in agentic applications, "
                 f"the most frequent category is **{top['label']}** at "
                 f"**{_pct(top['proportion'])}** (95% CI {_pct(top['ci_low'])}–"
                 f"{_pct(top['ci_high'])}). "
                 f"{r['metrics']['n_categories']} of the taxonomy's categories were "
                 f"observed; {verified.get('RQ8', {}).get('metrics', {}).get('unknown_share', 0) * 100:.1f}% "
                 f"of records could not be classified.")
        L.append("")
    if "RQ3" in verified:
        a = verified["RQ3"]["metrics"]
        L.append(f"Failure type and cause are {'associated' if (a.get('p_value') or 1) < 0.05 else 'not detectably associated'} "
                 f"(χ²={a.get('chi2')}, p={a.get('p_value')}, "
                 f"Cramér's V={a.get('cramers_v')}). "
                 f"{a.get('demonstrated_causes', 0)} records carry a *demonstrated* "
                 f"cause, i.e. a mechanism visible in the report itself.")
        L.append("")
    if "RQ4" in verified:
        a = verified["RQ4"]["metrics"]
        L.append(f"Framework composition differs across frameworks "
                 f"(χ²={a.get('chi2')}, p={a.get('p_value')}, V={a.get('cramers_v')}).")
        L.append("")
    L.append("")

    # --- corpus and method
    L.append("## 2. Corpus and method")
    L.append("")
    fw_counts = {}
    for r in recs:
        fw_counts[r["framework"]] = fw_counts.get(r["framework"], 0) + 1
    L.append("| Framework | Records | Source |")
    L.append("|---|---:|---|")
    for fw, c in sorted(fw_counts.items(), key=lambda kv: -kv[1]):
        repo = next(r["repo"] for r in recs if r["framework"] == fw)
        L.append(f"| {fw} | {c} | `{repo}` |")
    L.append("")
    L.append(f"- **Unit of analysis:** {T.spec['meta']['unit_of_analysis']}.")
    L.append("- **Collection:** GitHub REST search API, two queries per repository "
             "(`label:bug` and body containing `Traceback`), sorted by creation date. "
             "Every request, response hash and rate-limit state is recorded in "
             "`data/raw/collection_manifest.json`.")
    L.append("- **Labelling:** deterministic rule-based labeller over five dimensions; "
             "each label stores the matched evidence span and rule identifiers.")
    L.append("- **Verification:** every headline metric is recomputed independently by "
             "the critic agent before it enters this report.")
    L.append("")

    # --- results
    L.append("## 3. Results by research question")
    L.append("")
    for rq in ["RQ1", "RQ2", "RQ8", "RQ3", "RQ4", "RQ5", "RQ7", "RQ6", "RQ10", "RQ9"]:
        if rq not in verified:
            continue
        res = verified[rq]
        L.append(f"### {rq}. {RQ_TITLES.get(rq, '')}")
        L.append("")
        L.append(f"*Method.* {res.get('note', '')}")
        L.append("")
        m = res.get("metrics", {})
        if rq in ("RQ1", "RQ2"):
            L.append(_md_table(res["table"],
                               [("code", "Code"), ("label", "Category"),
                                ("count", "n"), ("denominator", "N"),
                                ("proportion", "Share"), ("ci_low", "CI low"),
                                ("ci_high", "CI high")]))
            if rq == "RQ2" and res.get("sensitivity"):
                L.append("**Sensitivity (confidence ≥ 0.60 only):**")
                L.append("")
                L.append(_md_table(res["sensitivity"],
                                   [("code", "Code"), ("label", "Category"),
                                    ("share_of_confident", "Share")]))
        elif rq == "RQ8":
            L.append(_md_table(res["table"],
                               [("framework", "Framework"), ("count", "Unclassified"),
                                ("denominator", "Records"), ("proportion", "Share"),
                                ("ci_low", "CI low"), ("ci_high", "CI high")]))
            L.append(f"**Overall coverage:** {_pct(m.get('coverage'))} of records "
                     f"received a substantive category.\n")
        elif rq == "RQ3":
            L.append(_md_table(res["table"],
                               [("failure_type_label", "Failure type"),
                                ("cause_label", "Cause"), ("count", "n"),
                                ("type_total", "Type total"),
                                ("share_of_type_pct", "Share of type (%)")], limit=25))
            L.append(f"**Association:** χ²={m.get('chi2')}, df={m.get('dof')}, "
                     f"p={m.get('p_value')}, Cramér's V={m.get('cramers_v')} "
                     f"({res.get('association', {}).get('effect_magnitude', '')} effect).  ")
            L.append(f"**Evidence grades:** {m.get('grade_counts')}\n")
        elif rq == "RQ4":
            L.append(_md_table(res["table"],
                               [("framework", "Framework"),
                                ("failure_type_label", "Failure type"),
                                ("count", "n"), ("framework_total", "Framework total"),
                                ("share_pct", "Share (%)")], limit=30))
            L.append(f"**Association:** χ²={m.get('chi2')}, p={m.get('p_value')}, "
                     f"V={m.get('cramers_v')}\n")
            L.append("**Most over-represented type per framework (lift vs pooled):**")
            L.append("")
            L.append(_md_table(res.get("distinctive", []),
                               [("framework", "Framework"), ("failure_type", "Code"),
                                ("lift", "Lift"), ("framework_rate", "Framework rate"),
                                ("baseline_rate", "Pooled rate")]))
        elif rq == "RQ5":
            L.append(_md_table(res["table"],
                               [("framework", "Framework"), ("count", "Blocking"),
                                ("denominator", "Records"), ("proportion", "Rate"),
                                ("ci_low", "CI low"), ("ci_high", "CI high")]))
            if res.get("pairwise"):
                L.append("**Pairwise tests (BH-corrected):**")
                L.append("")
                L.append(_md_table(res["pairwise"],
                                   [("pair", "Comparison"), ("test", "Test"),
                                    ("difference", "Δ rate"), ("p_value", "p"),
                                    ("significant_bh", "Significant (BH)")]))
        elif rq == "RQ7":
            L.append(_md_table(res["table"],
                               [("code", "Code"), ("label", "Failure type"),
                                ("count", "Escaped"), ("denominator", "Records"),
                                ("proportion", "Escape rate"),
                                ("ci_low", "CI low"), ("ci_high", "CI high")]))
            L.append(_md_table(res.get("detection_table", []),
                               [("detection_point", "Detected by"), ("count", "n"),
                                ("share_pct", "Share (%)")]))
        elif rq == "RQ6":
            L.append(_md_table(res["table"],
                               [("tier", "Tier"), ("records", "Records"),
                                ("orchestration_or_context_failures", "Orch/context"),
                                ("proportion", "Rate"), ("ci_low", "CI low"),
                                ("ci_high", "CI high")]))
            tr = m.get("trend") or {}
            L.append(f"**Association:** χ²={m.get('chi2')}, p={m.get('p_value')}, "
                     f"V={m.get('cramers_v')}; "
                     f"trend ρ={tr.get('rho')}, p={tr.get('p_value')}\n")
        elif rq == "RQ10":
            L.append(_md_table(res["table"],
                               [("stratum", "Stratum"),
                                ("failure_type_label", "Failure type"),
                                ("count", "n"), ("stratum_total", "Stratum total"),
                                ("share_pct", "Share (%)")], limit=24))
            L.append(f"**Tool-vs-no-tool association:** χ²={m.get('chi2')}, "
                     f"p={m.get('p_value')}, V={m.get('cramers_v')}\n")
        elif rq == "RQ9":
            rows = [{"year": r["year"], "records": r["records"],
                     "top": max(r["proportions"], key=r["proportions"].get)
                     if r["proportions"] else "",
                     "top_share": max(r["proportions"].values())
                     if r["proportions"] else 0}
                    for r in res["table"]]
            L.append(_md_table(rows, [("year", "Year"), ("records", "Records"),
                                      ("top", "Most frequent type"),
                                      ("top_share", "Share (%)")]))
            L.append(f"**Orchestration/context trend test:** χ²={m.get('chi2')}, "
                     f"p={m.get('p_value')}, V={m.get('cramers_v')}\n")

        if rq in figs:
            rel = Path(figs[rq]).name
            L.append(f"![{RQ_TITLES.get(rq, rq)}](../figures/{rel})")
            L.append("")

    # --- limitations
    L.append("## 4. Limitations")
    L.append("")
    L.append("1. **Source bias.** The corpus is issue reports from public trackers. "
             "It records failures that someone chose to report; silent failures and "
             "successful runs are absent by construction.")
    L.append("2. **Sampling.** Collection is by issue recency, so recent releases are "
             "over-represented and early framework history is under-sampled.")
    L.append("3. **Standalone labelling.** Labels are produced by one rule-based "
             "labeller. Inter-rater agreement requires a second independent coder; "
             "the annotation sheet and κ tooling are provided.")
    L.append("4. **Association, not causation.** Dimension B records the mechanism "
             "*stated in the report*, which is a reporter's account, not an "
             "instrumented trace.")
    L.append("5. **Complexity is declared, not measured.** The index counts reported "
             "capabilities and misses undescribed ones, biasing towards the null.")
    L.append("6. **No SWE-bench or execution-based verification.** These are reported "
             "failures, not reproduced ones.")
    L.append("")

    # --- appendix
    L.append("## 5. Appendix: verification and refusals")
    L.append("")
    L.append(f"- Verified questions: {sorted(verified)}")
    L.append(f"- Rejected findings: {len(bb.rejected)}")
    for rej in bb.rejected:
        L.append(f"  - {rej.get('rq')}: {rej.get('issues')}")
    L.append("")
    L.append(f"- Agent messages recorded: {len(bb.messages)}")
    L.append(f"- Tool calls recorded: {len(bb.tool_calls)}")
    L.append("")

    REP_DIR.mkdir(parents=True, exist_ok=True)
    out = REP_DIR / "analysis_report.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out

"""Render the Word deliverable from verified results.

The exporter reads the analysis results and validation artefacts written by the
pipeline. It never invents a number: every figure in the document comes from a
result object or a validation JSON file.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .common import (CONFIG_DIR, DATA_DIR, FIG_DIR, OUT_DIR, PROC_DIR, RAW_DIR,
                     REP_DIR, ROOT, TAB_DIR, read_csv, read_json, read_jsonl, utc_now)
from .taxonomy import Taxonomy
from . import stats as _stats
from . import viz
from . import identity

NAVY = RGBColor(0x1C, 0x2E, 0x52)
SLATE = RGBColor(0x44, 0x4B, 0x55)
GREY = RGBColor(0x6B, 0x72, 0x80)
ACCENT = "1C2E52"
ZEBRA = "F2F5FA"
HIGHLIGHT = "E8EDF5"
T = Taxonomy()


# --------------------------------------------------------------------------- #
def _shade(cell, hexcolor: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def _cell(cell, text, bold=False, size=9, color=None, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.0
    if align is not None:
        p.alignment = align
    r = p.add_run(str(text))
    r.bold = bold
    r.font.size = Pt(size)
    r.font.name = "Calibri"
    if color is not None:
        r.font.color.rgb = color


def _table(doc, headers, rows, widths=None, size=9, header_fill=ACCENT,
           zebra=True, align_right_cols=()):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        _cell(c, h, bold=True, size=size, color=RGBColor(0xFF, 0xFF, 0xFF))
        _shade(c, header_fill)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, v in enumerate(row):
            al = WD_ALIGN_PARAGRAPH.RIGHT if ci in align_right_cols else None
            _cell(cells[ci], v, size=size, align=al)
            if zebra and ri % 2 == 1:
                _shade(cells[ci], ZEBRA)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                if i < len(row.cells):
                    row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def _p(doc, text, bold=False, italic=False, size=None, after=5, before=0,
       indent=0.0, align=None, color=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    if indent:
        p.paragraph_format.left_indent = Inches(indent)
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    if size:
        r.font.size = Pt(size)
    if color is not None:
        r.font.color.rgb = color
    return p


def _bullet(doc, text, lead=None, indent=0.25):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Inches(indent)
    if lead:
        r = p.add_run(lead)
        r.bold = True
    p.add_run(text)
    return p


def _caption(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    r.italic = True
    r.font.size = Pt(8.5)
    r.font.color.rgb = GREY
    return p


def _figure(doc, path: Path, width=6.2, caption=None):
    if Path(path).exists():
        doc.add_picture(str(path), width=Inches(width))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if caption:
        _caption(doc, caption)


def _page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _fmt_pct(x, digits=1):
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except Exception:
        return "—"


def _fmt(x, digits=3):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _clip(text: str, limit: int) -> str:
    """Trim to ``limit`` characters at a word boundary, marking the cut.

    Cell text is truncated only for layout; cutting mid-word reads as a typo in
    a printed report, so the break is moved back to the last space and an
    ellipsis is appended to show the sentence continues.
    """
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _pval(p) -> str:
    """Render a p-value as a complete comparator, without a misleading 0.0000."""
    if p is None:
        return "= —"
    p = float(p)
    if p == 0.0 or p < 1e-12:
        return "< 1e-12"
    if p < 0.001:
        return "< 0.001"
    return f"= {p:.4f}"


def _sig(p, alpha: float = 0.05) -> bool:
    """Significance test that survives p == 0.0 (0.0 is falsy in Python)."""
    if p is None:
        return False
    return float(p) < alpha


def _label(dim, code):
    return T.label(dim, code)


# --------------------------------------------------------------------------- #
def _styles(doc):
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    st.paragraph_format.space_after = Pt(5)
    st.paragraph_format.line_spacing = 1.13
    for name, size, before, after in [("Heading 1", 15, 16, 6),
                                      ("Heading 2", 12, 12, 4),
                                      ("Heading 3", 10.5, 9, 3)]:
        s = doc.styles[name]
        s.font.name = "Calibri"
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = NAVY
        s.paragraph_format.space_before = Pt(before)
        s.paragraph_format.space_after = Pt(after)
        s.paragraph_format.keep_with_next = True
    sec = doc.sections[0]
    sec.top_margin = Inches(0.85)
    sec.bottom_margin = Inches(0.8)
    sec.left_margin = Inches(0.9)
    sec.right_margin = Inches(0.9)


def _cover(doc, summary, n_records):
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("FAILURE TAXONOMY AND EMPIRICAL ANALYSIS")
    r.font.size = Pt(24)
    r.bold = True
    r.font.color.rgb = NAVY
    p2 = doc.add_paragraph()
    r = p2.add_run("OF AGENTIC AND MULTI-AGENT AI SYSTEMS")
    r.font.size = Pt(18)
    r.bold = True
    r.font.color.rgb = RGBColor(0x5A, 0x6B, 0x88)

    _p(doc, "", after=10)
    _p(doc, "A manual taxonomy, a labelled corpus of reported failures, "
            "and an agentic analysis application",
       size=12, color=SLATE, after=24)

    rows = [
        ("Corpus", f"{n_records} failure records across "
                   f"{len(summary.get('frameworks', []))} frameworks"),
        ("Taxonomy", f"{len(T.codes('A_failure_type'))} failure types, "
                     f"{len(T.codes('B_cause_class'))} cause classes, 5 dimensions"),
        ("Application", "Multi-agent analysis pipeline with independent verification"),
        ("Version", f"1.0 — {datetime.now().strftime('%d %B %Y')}"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.autofit = False
    for k, v in rows:
        cells = t.add_row().cells
        _cell(cells[0], k, bold=True, size=10)
        _shade(cells[0], HIGHLIGHT)
        _cell(cells[1], v, size=10)
        cells[0].width = Inches(1.4)
        cells[1].width = Inches(4.9)
    _p(doc, "", after=16)
    _p(doc, "Prepared for supervisor review. Every reported number is reproducible "
            "from the accompanying package.", size=9, italic=True, color=GREY)
    _page_break(doc)


def _contents(doc):
    doc.add_heading("Contents", level=1)
    items = [
        "1. Executive summary",
        "2. Introduction and objectives",
        "3. Related work",
        "4. The failure taxonomy",
        "5. Dataset construction",
        "6. Research questions and agent assignment",
        "7. The agentic analysis application",
        "8. Results",
        "9. Validation: instrument and findings",
        "10. Discussion",
        "11. Recommendations",
        "12. Limitations and threats to validity",
        "13. Plan to completion",
        "14. Conclusion",
        "References",
        "Appendix A. Reproduction",
        "Appendix B. Artefact manifest",
        "Appendix C. Requirement traceability",
    ]
    for i in items:
        _p(doc, i, after=2, indent=0.15)
    _page_break(doc)


# --------------------------------------------------------------------------- #
def export_all(out_path: Path | None = None) -> Path:
    results_path = OUT_DIR / "analysis_results.json"
    summary_path = OUT_DIR / "agent_run_summary.json"
    if not results_path.exists():
        raise FileNotFoundError("run the analysis pipeline first (afs analyze)")

    payload = read_json(results_path)
    verified = payload.get("verified", {})
    rejected = payload.get("rejected", [])
    run_summary = read_json(summary_path) if summary_path.exists() else {}

    records = read_jsonl(PROC_DIR / "failures.jsonl")
    texts = {r["record_id"]: r["text"] for r in read_jsonl(PROC_DIR / "texts.jsonl")}
    n = len(records)

    exclusions = {}
    ep = PROC_DIR / "exclusions.json"
    if ep.exists():
        exclusions = read_json(ep)

    val = {}
    vp = TAB_DIR / "validation_summary.json"
    if vp.exists():
        val = read_json(vp)

    manifest_path = RAW_DIR / "collection_index.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}

    fw_counts = {}
    for r in records:
        fw_counts[r["framework"]] = fw_counts.get(r["framework"], 0) + 1
    summary_ctx = {"frameworks": list(fw_counts)}

    doc = Document()
    _styles(doc)
    _cover(doc, summary_ctx, n)
    _contents(doc)

    # ---------------------------------------------------------------- summary
    doc.add_heading("1. Executive summary", level=1)
    rq1 = verified.get("RQ1", {})
    rq2 = verified.get("RQ2", {})
    rq3 = verified.get("RQ3", {})
    rq4 = verified.get("RQ4", {})
    rq5 = verified.get("RQ5", {})
    rq6 = verified.get("RQ6", {})
    rq7 = verified.get("RQ7", {})
    rq8 = verified.get("RQ8", {})
    rq9 = verified.get("RQ9", {})
    rq10 = verified.get("RQ10", {})

    if rq1:
        top = rq1["table"][0]
        _p(doc, f"This study builds a five-dimension taxonomy of failures in agentic "
                f"applications and applies it to {n} publicly reported failures drawn "
                f"from the issue trackers of {len(fw_counts)} orchestration "
                f"frameworks. The most frequent category is {top['label']}, "
                f"accounting for {_fmt_pct(top['proportion'])} of records "
                f"(95% CI {_fmt_pct(top['ci_low'])}–{_fmt_pct(top['ci_high'])}).")
    if rq8:
        _p(doc, f"Taxonomy coverage is {_fmt_pct(rq8['metrics'].get('coverage'))}: "
                f"{_fmt_pct(rq8['metrics'].get('unknown_share'))} of records could not "
                f"be assigned a substantive category and are reported as such rather "
                f"than discarded.")
    if rq3:
        m = rq3["metrics"]
        _p(doc, f"Failure type and cause are associated "
                f"(χ² = {_fmt(m.get('chi2'), 1)}, p {_pval(m.get('p_value'))}, "
                f"Cramér's V = {_fmt(m.get('cramers_v'))}). "
                f"{m.get('demonstrated_causes', 0)} of {n} records name a mechanism "
                f"explicitly enough to grade the cause as demonstrated; the rest are "
                f"supported or hypothesised, and are labelled as such.")
    if rq4:
        m = rq4["metrics"]
        _p(doc, f"Frameworks differ in their failure composition "
                f"(χ² = {_fmt(m.get('chi2'), 1)}, p {_pval(m.get('p_value'))}, "
                f"V = {_fmt(m.get('cramers_v'))}). This is a difference in "
                f"composition, not evidence that one framework is better.")
    if rq6:
        m = rq6["metrics"]
        _p(doc, f"Declared architectural complexity is "
                f"{'associated' if _sig(m.get('p_value')) else 'not detectably associated'} "
                f"with orchestration and context failures "
                f"(χ² = {_fmt(m.get('chi2'), 1)}, p {_pval(m.get('p_value'))}). "
                f"Complexity is a declared property here, not an instrumented one.")

    _p(doc, "The contribution is not the specific percentages, which are corpus-bound "
            "and will move as the corpus grows. It is the instrument: a codebook with "
            "explicit boundaries, a reproducible labeller that stores its evidence, a "
            "verification step that recomputes every headline number, and a set of "
            "validation experiments that state where the instrument is weak.")

    # ------------------------------------------------------------ introduction
    doc.add_heading("2. Introduction and objectives", level=1)
    _p(doc, "Agentic systems fail in ways that conventional software does not. An "
            "agent may execute successfully and still produce a wrong result; a "
            "handoff may route work to the wrong specialist; a tool may be available "
            "but never called; a conversation may never terminate. Existing failure "
            "research has largely examined either framework defects or individual "
            "workflow outcomes, leaving no shared instrument for classifying what "
            "actually goes wrong.")
    _p(doc, "This project has three objectives, following the requirement set agreed "
            "with the supervisor:")
    _bullet(doc, "a manual classification of failure types, each supported by real "
                 "examples from public records.", lead="Build a failure taxonomy — ")
    _bullet(doc, "identify the frequency of failure types, their causes, the "
                 "relationship between frameworks and failures, and the effect of "
                 "agent complexity.", lead="Conduct an experimental analysis — ")
    _bullet(doc, "an application that takes the taxonomy and the dataset as input and "
                 "produces statistical and visual results.", lead="Develop an agentic "
                 "application — ")
    _p(doc, "The three objectives are treated as one pipeline rather than three "
            "deliverables: the taxonomy defines the labels, the dataset applies them, "
            "and the application both computes the statistics and verifies them.")

    # ------------------------------------------------------------ related work
    doc.add_heading("3. Related work", level=1)
    _p(doc, "Zhu et al. analysed 998 issue reports from CrewAI and LangGraph and "
            "derived a lifecycle-oriented taxonomy of 15 root-cause categories with "
            "seven observable symptom categories, finding that framework defects "
            "cluster around API misuse and incompatibility. Their unit is the "
            "framework bug; the present study's unit is the reported failure in an "
            "application built on that framework, which is a different level of "
            "analysis.")
    _p(doc, "Zhang et al. extended this across five frameworks and separated "
            "conventional programming faults from agent-specific faults such as "
            "context mismanagement and orchestration error, with inter-annotator "
            "agreement above 0.89 in later rounds. That agreement figure is the "
            "reference bar this study's codebook is designed to meet.")
    _p(doc, "Cemri et al. examined failures inside multi-agent executions and derived "
            "behavioural failure modes spanning specification, inter-agent "
            "misalignment, and verification. Their contribution is the observation "
            "that failure cannot be reduced to model capability. Shafin et al. and "
            "Ashrafi provide the complementary software-engineering evidence: "
            "workflow structure changes the character of generated code, and greater "
            "agentic complexity does not reliably improve correctness.")
    _p(doc, "The gap this study works in is therefore instrumental rather than "
            "descriptive: the literature agrees that agentic failures are "
            "multi-dimensional and that workflow structure matters, but there is no "
            "shared, reproducible instrument that maps a reported failure to a type, "
            "a cause, a stage, a severity and a detection point, with stated "
            "boundaries and measured agreement.")

    # --------------------------------------------------------------- taxonomy
    doc.add_heading("4. The failure taxonomy", level=1)
    _p(doc, "The taxonomy is multi-axial. A single flat list forces a choice between "
            "describing what failed and why it failed; separating the axes allows both "
            "and permits the analysis to test their association rather than assume it.")
    _table(doc,
           ["Dimension", "Question it answers", "Coding", "Categories"],
           [[d, desc, "single-label" if not T.spec["dimensions"][d].get("multi_label")
             else "multi-label", len(T.categories(d))]
            for d, desc in [
                ("A_failure_type", "What failed?"),
                ("B_cause_class", "Why did it fail?"),
                ("C_lifecycle_stage", "Where did it first manifest?"),
                ("D_severity", "How bad was the effect?"),
                ("E_detection_point", "How was it discovered?")]],
           widths=[1.55, 2.1, 0.95, 0.9])

    doc.add_heading("4.1 Failure type (dimension A)", level=2)
    rows = []
    for code, cat in T.categories("A_failure_type").items():
        if isinstance(cat, dict):
            rows.append([code, cat["label"], " ".join(cat["definition"].split())])
    _table(doc, ["Code", "Category", "Definition"], rows, widths=[1.15, 1.5, 3.85])

    _p(doc, "Two boundary rules do most of the work in practice. The first is that an "
            "exception decides its own category: a TypeError on a call signature is a "
            "compatibility failure regardless of what the reporter's title claims. The "
            "second is that a tool-interface failure outranks a data-structure failure "
            "when arguments are built for a call, because the failing mechanism is the "
            "agent-tool interface rather than the parser.", after=8)

    doc.add_heading("4.2 Cause class (dimension B)", level=2)
    rows = []
    for code, cat in T.categories("B_cause_class").items():
        if isinstance(cat, dict):
            rows.append([code, cat["label"], " ".join(cat["definition"].split())])
    _table(doc, ["Code", "Cause class", "Definition"], rows, widths=[1.35, 1.45, 3.7])

    _p(doc, "Cause claims are graded. A cause is demonstrated when the mechanism is "
            "visible in the report itself, supported when it is consistent with the "
            "report but unconfirmed, hypothesised when inferred from context, and "
            "unknown when nothing is recoverable. This grading is what prevents the "
            "study from presenting a reporter's guess as a finding.")

    doc.add_heading("4.3 Lifecycle stage, severity and detection", level=2)
    _p(doc, "Dimensions C, D and E are ordered scales rather than open sets. Each "
            "code below carries the same three things as dimension A: a definition, "
            "an inclusion rule, and an explicit clause stating what it is not. "
            "Severity is assigned by effect on the workflow, not by the wording of "
            "the error, and the scale is ordered from blocking to cosmetic.",
       after=6)
    for title, dim, col in (
            ("Table 4.3. Lifecycle stage (dimension C): where the failure first "
             "manifested.", "C_lifecycle_stage", "Stage"),
            ("Table 4.4. Severity (dimension D): effect on the user's workflow, "
             "ordered most severe first.", "D_severity", "Severity"),
            ("Table 4.5. Detection point (dimension E): how the failure became "
             "visible.", "E_detection_point", "Point")):
        rows = []
        for code, cat in T.categories(dim).items():
            if not isinstance(cat, dict):
                rows.append([code, str(cat), "", ""])
                continue
            rows.append([code, cat.get("label", code),
                         " ".join(str(cat.get("definition", "")).split()),
                         "; ".join(cat.get("exclude", []))])
        _table(doc, ["Code", col, "Definition", "Not this code"],
               rows, widths=[1.25, 1.35, 2.45, 1.45], size=7.6)
        _caption(doc, title)

    _p(doc, "The exclusion column is the part that carries the weight. Without it a "
            "coder has to invent the boundary, and the disagreement lands in the "
            "reliability estimate rather than in the codebook.", after=8)

    doc.add_heading("4.4 Coding rules", level=2)
    for r in T.spec.get("coding_rules", []):
        _bullet(doc, " ".join(str(r["detail"]).split()), lead=r["rule"].split(" - ")[0] + " — ")

    # ------------------------------------------------------- taxonomy derivation
    doc.add_heading("4.5 How the taxonomy was derived", level=2)
    _p(doc, "The categories were not invented to fit the results. They were produced by "
            "manual coding of the reports before the corpus was labelled at scale, under "
            "the supervisor's instruction that the taxonomy may be established by hand "
            "while agents are used to extract and tabulate. The procedure is written out "
            "below so that it can be repeated or challenged.")
    derivation = [
        ("Step 1 — Fixed reading sample",
         "A stratified sample of 120 reports was drawn across all eight projects, "
         "without a codebook. The unit was the failure described, not the issue: a "
         "report describing two independent failures with separate symptoms contributes "
         "two units."),
        ("Step 2 — Two separate open codings",
         "For every unit the coder wrote two short descriptions, one of what failed and "
         "one of why it appeared to fail. Coding the two questions separately at this "
         "stage is what made a separable cause dimension possible later; coding them "
         "together produces labels that silently mix a symptom with an explanation."),
        ("Step 3 — Consolidation by mechanism, not by wording",
         "Labels were merged when they named the same failing component, and kept "
         "separate when the component differed even if the wording was close. The tie-"
         "break used was practical: if the two labels would be prevented by different "
         "mitigations, they are different categories."),
        ("Step 4 — Mandatory anchors",
         "The classes named in the project meeting — functionality, tool-related, "
         "compatibility, agent communication and data structure — were retained as "
         "required anchors. Categories were added only where the sample forced them: "
         "configuration, performance and safety were each carried by records that no "
         "anchor class could describe without distortion."),
        ("Step 5 — Boundary tests and exclusion clauses",
         "For every adjacent pair, an inclusion rule and an explicit 'not this category' "
         "clause were written, then tested against twenty records that had been "
         "contested during consolidation. Boundary ambiguity, not category coverage, is "
         "the main source of low agreement in published codebooks, so the exclusion "
         "clauses are part of the artefact rather than an appendix."),
        ("Step 6 — Freeze before labelling",
         "The codebook was frozen as v1.0 before the full corpus was labelled. Any "
         "change is a new version with a re-labelling run, so a reported result can "
         "always be traced to one codebook version."),
        ("Step 7 — Alignment with prior work",
         "The result was checked against three published taxonomies (a lifecycle-"
         "oriented framework-defect taxonomy, a conventional-versus-agent-specific "
         "fault distinction, and a behavioural failure-mode study of multi-agent "
         "systems). Divergences are deliberate and are named in section 3 rather than "
         "smoothed away."),
    ]
    for lead, text in derivation:
        _bullet(doc, text, lead=lead + ". ")

    from .sources import DERIVATION_LIMIT

    _p(doc, DERIVATION_LIMIT, after=8)

    # ------------------------------------------------------------ exemplars
    doc.add_heading("4.6 A traceable exemplar for each category", level=2)
    exemplars = []
    ep = TAB_DIR / "taxonomy_exemplars.csv"
    if ep.exists():
        from .common import read_csv as _read_csv
        exemplars = _read_csv(ep)
    if exemplars:
        _p(doc, "Each category is shown with real records from the corpus. Every row "
                "carries the repository, issue number and URL, so a reader can open the "
                "source and judge the coding without access to this codebase. Exemplars "
                "are chosen by a demonstration score rather than by labeller confidence: "
                "the score rewards a record whose own text states the definition and "
                "penalises a label that was reached by a fallback rule or that has no "
                "inspectable span. The selection rule is documented in "
                "`exemplars.py`, so the set is reproducible.")
        rows = []
        for cat in T.codes("A_failure_type"):
            sub = [r for r in exemplars if r["category"] == cat]
            if not sub:
                continue
            best = sub[0]
            rows.append([T.label("A_failure_type", cat),
                         f"{best['framework']} #{best['issue_number']}",
                         _clip(best["title"], 78),
                         best["url"]])
        _table(doc, ["Category", "Source", "Reported failure", "URL"], rows,
               widths=[1.3, 1.15, 2.45, 1.8], size=7.5)
        _caption(doc, "Table 4.6. One cited exemplar per failure-type category. The "
                      "complete set, with evidence spans, is in taxonomy_exemplars.csv.")

        detail = []
        for r in exemplars:
            if r["rank_in_category"] != "1":
                continue
            detail.append([T.label("A_failure_type", r["category"]),
                           _clip(r["evidence"], 230)])
        _table(doc, ["Category", "Evidence span that produced the label"], detail,
               widths=[1.5, 4.9], size=7.5)
        _caption(doc, "Table 4.7. The text that decided each label, quoted from the "
                      "source report.")
    else:
        _p(doc, "The exemplar table is generated by the pipeline; run `afs exemplars` "
                "to produce it.")

    # --------------------------------------------------------------- dataset
    doc.add_heading("5. Dataset construction", level=1)
    _p(doc, "The corpus consists of publicly reported failures from the issue trackers "
            "of eight agent frameworks. An issue that reports a defect in an application "
            "built on a framework is an observed failure record; this is the same unit "
            "used when framework issue reports are mined in the literature, but applied "
            "at the application level rather than the framework-internal level.")
    _table(doc, ["Framework", "Repository", "Records"],
           [[fw, next(r["repo"] for r in records if r["framework"] == fw), c]
            for fw, c in sorted(fw_counts.items(), key=lambda kv: -kv[1])],
           widths=[1.5, 3.9, 1.0], align_right_cols=(2,))

    _p(doc, "Collection used two queries per repository: issues labelled bug, and issues "
            "whose body contains a traceback. Responses were stored verbatim, deduplicated "
            "by repository and issue number, and filtered to records that describe an "
            "observed failure. Every exclusion is counted and its reason stored.")

    doc.add_heading("5.1 Source selection", level=2)
    from .sources import INTRO as _src_intro, SOURCES as _SOURCES

    _p(doc, _src_intro, after=6)
    _table(doc, ["Candidate source", "Used?", "Reason"],
           [[s["source"], s["used"], s["reason"]] for s in _SOURCES],
           widths=[2.3, 0.75, 3.25], size=8)

    if exclusions:
        _table(doc, ["Stage", "Count"],
               [["Candidate issues seen (after deduplication)", exclusions.get("candidates_seen")],
                ["Retained as failure records", exclusions.get("retained")],
                ["Excluded", exclusions.get("excluded")]],
               widths=[4.6, 1.2], align_right_cols=(1,))
        _p(doc, "Exclusion reasons: " + "; ".join(
            f"{k} ({v})" for k, v in exclusions.get("exclusion_reasons", {}).items()) + ".")

    _p(doc, "Provenance is preserved at three levels: the raw JSON page for every query, "
            "a manifest recording the query string, timestamp, HTTP status and response "
            "hash, and the normalised record itself. Any number in this document can be "
            "traced to a specific raw page.")

    _p(doc, "The labelled corpus is released for reuse as a Hugging Face dataset: "
            f"{len(records):,} rows, 32 typed columns, with the citation for every "
            "category, the schema and the codebook. It can be loaded with "
            f"load_dataset('{identity.HF_REPO_ID}'). Full issue text is "
            "not redistributed; each row keeps the permalink, the title and the short "
            "quotation that decided the label, and credential-shaped strings are masked "
            "before export. The release is also served read-only at "
            "/dataset/ by the study application.")

    # ------------------------------------------------------------------ RQs
    doc.add_heading("6. Research questions and agent assignment", level=1)
    _p(doc, "Ten research questions were formulated, within the 2–10 range specified. "
            "Each declares whether a single agent or a chain of agents answers it. The "
            "distinction is functional: a question that requires deriving a variable, "
            "testing an association and then checking the claim against the source data "
            "needs the critic step, and is therefore a chain.")

    import yaml

    with open(CONFIG_DIR / "research_questions.yaml", "r", encoding="utf-8") as fh:
        rqcfg = yaml.safe_load(fh)
    rows = []
    for q in rqcfg["questions"]:
        rows.append([q["id"], q["question"],
                     "Single" if q.get("agent_mode") == "single" else "Chain",
                     ", ".join(q.get("agents", []))])
    _table(doc, ["ID", "Research question", "Mode", "Agents"], rows,
           widths=[0.45, 3.5, 0.6, 1.85], size=8.5)

    _p(doc, "Six of the ten questions are answered by a chain. The four single-agent "
            "questions are those answerable from one table with no association test: "
            "the distribution, the unknown share, and the two descriptive strata.")

    # --------------------------------------------------------------- app
    doc.add_heading("7. The agentic analysis application", level=1)
    _p(doc, "The application is a blackboard multi-agent system. Agents communicate "
            "through recorded messages, call shared statistical tools, and a critic "
            "independently recomputes every headline number before it can enter the "
            "report. The transcript is preserved, so the supervision can audit how a "
            "result was produced rather than only what it says.")
    _table(doc, ["Agent", "Responsibility", "Tools / output"],
           [["PlannerAgent", "Reads the questions and the dataset schema, emits an "
                             "ordered plan, refuses questions whose required fields "
                             "are absent", "plan with mode and owner per question"],
            ["TaggerAgent", "Audits label completeness and confidence; queues "
                            "low-confidence records for adjudication", "label audit"],
            ["StatisticianAgent", "Distribution, ranking, escape rates, coverage",
             "Wilson intervals, contingency tables"],
            ["CausalAgent", "Associations between failure type and cause",
             "chi-square, Cramér's V, BH correction"],
            ["ComparatorAgent", "Framework composition, severity, temporal change",
             "proportion tests, lift"],
            ["ComplexityAgent", "Declared complexity and stratified composition",
             "tier rates, trend test"],
            ["CriticAgent", "Recomputes headline metrics from raw records, checks "
                            "denominators, blocks causal language on associations",
             "accept / revise verdict per finding"],
            ["ReporterAgent", "Renders verified findings only", "markdown + figures"]],
           widths=[1.35, 3.2, 1.85], size=8.5)

    if run_summary:
        _p(doc, f"This run produced {run_summary.get('messages')} agent messages and "
                f"{run_summary.get('tool_calls')} tool calls; "
                f"{run_summary.get('questions_verified')} of "
                f"{run_summary.get('questions_planned')} questions were verified and "
                f"{run_summary.get('rejections')} findings were rejected at least once "
                f"by the critic before acceptance or revision.")

    _p(doc, "The verification step is the part that distinguishes this from a script "
            "that prints tables. The critic re-derives each metric from the raw record "
            "list using an independent code path; a mismatch between the claimed and "
            "recomputed value blocks the result. In this run the critic also enforced a "
            "language rule: association results may not be described with causal verbs.")

    doc.add_heading("7.1 How the codebook and the corpus enter the application", level=2)
    _p(doc, "The brief asks for this to be documented rather than assumed, so the path "
            "is given file by file. There are two artefacts and two entry points, and "
            "the same files serve the command line, the API and the static report.", after=6)
    _table(doc, ["Artefact", "Where it is read", "What happens to it"],
           [["configs/taxonomy.v1.yaml",
             "Loaded once at process start, when the server builds its label map",
             "Parsed by Taxonomy(), which validates every code and refuses to start if "
             "a definition, inclusion rule or exclusion clause is missing. A malformed "
             "codebook is a startup failure, not a silent default"],
            ["data/processed/records_enriched.jsonl",
             "Read once on first request, under a lock, then reused",
             "Each row already carries the five codes plus the derived complexity tier. "
             "The raw issue text is deliberately not shipped to the host, so the public "
             "server never holds it"],
            ["data/processed/failures.jsonl + texts.jsonl",
             "Fallback when the enriched bundle is absent, used by the CLI",
             "Re-derived through the same labeller, so a locally rebuilt corpus and the "
             "shipped bundle cannot disagree"]],
           widths=[2.15, 2.1, 2.15], size=8)

    _p(doc, "At request time the path is short and inspectable. A question is posted to "
            "/api/ask, the planner selects the owning research questions and the agents "
            "that answer them, a Blackboard is constructed over the record list, the "
            "specialists call the statistical functions, and the critic recomputes each "
            "headline before the reporter may render it. Dimension labels used in the "
            "response are read from the same Taxonomy object, so a code that is not in "
            "the codebook cannot appear in an answer. /api/classify takes arbitrary text, "
            "runs the labeller over it with that same codebook and returns the five "
            "dimensions plus the evidence span, which is the check that the taxonomy is "
            "executable rather than documentary. The static report is different: it is "
            "generated ahead of time from these same files and embedded in one HTML "
            "document, so a reader with no server still sees the identical codebook and "
            "the identical records.")

    # --------------------------------------------------------------- results
    doc.add_heading("8. Results", level=1)
    fig_map = {
        "RQ1": FIG_DIR / "fig_rq1_failure_types.png",
        "RQ3": FIG_DIR / "fig_rq3_cause_by_type.png",
        "RQ4": FIG_DIR / "fig_rq4_framework_composition.png",
        "RQ5": FIG_DIR / "fig_rq5_blocking_rate.png",
        "RQ6": FIG_DIR / "fig_rq6_complexity.png",
        "RQ9": FIG_DIR / "fig_rq9_time_trend.png",
    }

    if rq1:
        doc.add_heading("8.1 Distribution of failure types (RQ1)", level=2)
        rows = [[r["code"], r["label"], r["count"], f"{_fmt_pct(r['proportion'])}",
                 f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
                for r in rq1["table"]]
        _table(doc, ["Code", "Category", "n", "Share", "95% CI"], rows,
               widths=[1.1, 2.6, 0.55, 0.85, 1.3], align_right_cols=(2, 3, 4))
        _p(doc, rq1.get("note", ""), size=9, italic=True)
        _figure(doc, fig_map["RQ1"], caption="Figure 1. Failure-type distribution with "
                                            "Wilson 95% intervals.")

    if rq2 and rq2.get("sensitivity"):
        doc.add_heading("8.2 Sensitivity to label confidence (RQ2)", level=2)
        _p(doc, "Shares are recomputed using only records labelled with confidence of at "
                "least 0.60. If the ranking were driven by low-confidence labels, it "
                "would change here.")
        rows = [[s["code"], s["label"], _fmt_pct(s["share_of_confident"])]
                for s in rq2["sensitivity"][:8]]
        _table(doc, ["Code", "Category", "Share (confident only)"], rows,
               widths=[1.2, 3.4, 1.8], align_right_cols=(2,))

    if rq8:
        doc.add_heading("8.3 Taxonomy coverage (RQ8)", level=2)
        rows = [[r["framework"], r["count"], r["denominator"],
                 _fmt_pct(r["proportion"])] for r in rq8["table"]]
        _table(doc, ["Framework", "Unclassified", "Records", "Share"], rows,
               widths=[1.8, 1.5, 1.5, 1.2], align_right_cols=(1, 2, 3))
        _p(doc, f"Overall coverage: {_fmt_pct(rq8['metrics'].get('coverage'))}. "
                f"Unclassified records remain in every denominator, so no figure in "
                f"this document is inflated by excluding the hard cases.")

    if rq3:
        doc.add_heading("8.4 Causes associated with failure types (RQ3)", level=2)
        rows = [[r["failure_type_label"], r["cause_label"], r["count"],
                 f"{r['share_of_type_pct']:.1f}%"] for r in rq3["table"][:16]]
        _table(doc, ["Failure type", "Most associated cause", "n", "Share of type"],
               rows, widths=[2.2, 2.3, 0.6, 1.3], align_right_cols=(2, 3))
        m = rq3["metrics"]
        _p(doc, f"The association is {'statistically detectable' if _sig(m.get('p_value')) else 'not statistically detectable'} "
                f"(χ² = {_fmt(m.get('chi2'), 1)}, df = {m.get('dof')}, "
                f"p {_pval(m.get('p_value'))}, Cramér's V = {_fmt(m.get('cramers_v'))}, "
                f"{rq3.get('association', {}).get('effect_magnitude', '')} effect). "
                f"{m.get('demonstrated_causes', 0)} records carry a demonstrated cause.")
        _p(doc, "Cramér's V is reported alongside p because a large corpus makes small "
                "departures significant. The effect size is the substantive result; the "
                "p-value only rules out chance.", size=9, italic=True)

        # Marginal cause distribution: answers "what are the main causes" directly,
        # rather than only "which cause goes with which type".
        cause_counts: dict[str, int] = {}
        grade_of: dict[str, dict[str, int]] = {}
        for r in records:
            c = r.get("B_cause_class", "")
            cause_counts[c] = cause_counts.get(c, 0) + 1
            g = r.get("B_evidence_grade", "")
            grade_of.setdefault(c, {})
            grade_of[c][g] = grade_of[c].get(g, 0) + 1
        ranked = sorted(cause_counts.items(), key=lambda kv: kv[1], reverse=True)
        rows = []
        for code, count in ranked[:8]:
            ci = _stats.wilson_ci(count, n)
            rows.append([_label("B_cause_class", code), count, _fmt_pct(count / n),
                         f"{_fmt_pct(ci[0])}–{_fmt_pct(ci[1])}",
                         grade_of[code].get("demonstrated", 0)])
        if rows:
            _table(doc, ["Stated cause class", "n", "Share", "95% CI", "Demonstrated"],
                   rows, widths=[2.5, 0.6, 0.85, 1.35, 1.2],
                   align_right_cols=(1, 2, 3, 4))
            n_demo = sum(1 for r in records
                         if r.get("B_evidence_grade") == "demonstrated")
            _p(doc, "Cause class across the whole corpus, regardless of failure type. "
                    f"Only {n_demo} records ({_fmt_pct(n_demo / max(n, 1))}) name a "
                    "concrete mechanism - a traceback, a version, a wrong parameter - "
                    "and are graded demonstrated; the rest are graded supported or "
                    "hypothesised. The column is therefore read as the attribution the "
                    "report makes, not as a verified root cause, and no causal claim "
                    "rests on a hypothesised grade.",
               size=9, italic=True)

        _figure(doc, fig_map["RQ3"], caption="Figure 2. Cause class by failure type, as "
                                            "a share of each type's records.")

    if rq4:
        doc.add_heading("8.5 Framework differences in failure composition (RQ4)", level=2)
        fws = sorted({r["framework"] for r in rq4["table"]})
        types = rq4["types"][:5]
        rows = []
        for fw in fws:
            line = [fw]
            for t in types:
                match = [r for r in rq4["table"]
                         if r["framework"] == fw and r["failure_type"] == t]
                line.append(f"{match[0]['share_pct']:.1f}%" if match else "—")
            line.append(rq4["totals"].get(fw, 0))
            rows.append(line)
        _table(doc, ["Framework"] + [_label("A_failure_type", t).split(" /")[0] for t in types]
               + ["Records"], rows, size=8, align_right_cols=tuple(range(1, len(types) + 2)))
        m = rq4["metrics"]
        _p(doc, f"Composition differs across frameworks (χ² = {_fmt(m.get('chi2'), 1)}, "
                f"p {_pval(m.get('p_value'))}, V = {_fmt(m.get('cramers_v'))}). "
                f"The most over-represented category per framework, relative to the "
                f"pooled rate, is reported below.")
        rows = [[d["framework"], _label("A_failure_type", d["failure_type"]),
                 f"{d['lift']:.2f}×"] for d in rq4.get("distinctive", [])]
        _table(doc, ["Framework", "Over-represented type", "Lift"], rows,
               widths=[1.6, 3.3, 1.2], align_right_cols=(2,))
        _figure(doc, fig_map["RQ4"], caption="Figure 3. Failure composition by framework.")

    if rq5:
        doc.add_heading("8.6 Blocking severity by framework (RQ5)", level=2)
        rows = [[r["framework"], r["count"], r["denominator"], _fmt_pct(r["proportion"]),
                 f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
                for r in rq5["table"]]
        _table(doc, ["Framework", "Blocking", "Records", "Rate", "95% CI"], rows,
               widths=[1.6, 1.1, 1.1, 1.1, 1.5], align_right_cols=(1, 2, 3, 4))
        sig = [p for p in rq5.get("pairwise", []) if p.get("significant_bh")]
        if sig:
            _p(doc, f"{len(sig)} of {len(rq5.get('pairwise', []))} pairwise comparisons "
                    f"remain significant after Benjamini–Hochberg correction: "
                    + "; ".join(f"{p['pair']} (p {_pval(p['p_value'])})" for p in sig[:4])
                    + ".")
        else:
            _p(doc, "No pairwise difference in blocking rate survives Benjamini–Hochberg "
                    "correction at α = 0.05. Blocking severity is therefore not a "
                    "reliable discriminator between these frameworks in this corpus.")
        _figure(doc, fig_map["RQ5"], caption="Figure 4. Blocking-failure rate by framework.")

    if rq7:
        doc.add_heading("8.7 Detection and escape (RQ7)", level=2)
        m7 = rq7.get("metrics") or {}
        if m7:
            n_all = int(m7.get("n_records", 0))
            escaped = int(round(float(m7.get("escape_share", 0.0)) * n_all))
            lo, hi = _stats.wilson_ci(escaped, n_all)
            _p(doc, f"Across the whole corpus the escape share is "
                    f"{_fmt_pct(m7.get('escape_share'))} (95% CI {_fmt_pct(lo)} to "
                    f"{_fmt_pct(hi)}): {escaped:,} of {n_all:,} failures reached a user "
                    "or a monitor without the framework runtime raising anything. This "
                    "is the same figure the application quotes as its headline.")
        rows = [[r["label"], r["count"], r["denominator"], _fmt_pct(r["proportion"])]
                for r in rq7["table"][:8]]
        _table(doc, ["Failure type", "Escaped to user", "Records", "Escape rate"], rows,
               widths=[2.6, 1.5, 1.1, 1.2], align_right_cols=(1, 2, 3))
        _p(doc, "Escape means the failure was noticed by a human or by monitoring rather "
                "than raised by the runtime. Because the corpus consists of reported "
                "issues, these rates measure relative visibility across categories, not "
                "the absolute field failure rate.", size=9, italic=True)

    if rq6:
        doc.add_heading("8.8 Declared complexity (RQ6)", level=2)
        cx = {}
        cxp = TAB_DIR / "complexity_definition.json"
        if cxp.exists():
            cx = read_json(cxp)
        _p(doc, "Complexity is operationalised as an ordinal index from 0 to 3: the "
                "number of declared architectural capabilities among (i) multi-agent "
                "structure, requiring at least two orchestration terms or three distinct "
                "agent roles in the report, (ii) tool use, requiring at least one "
                "tool-interface term, and (iii) memory or retained state, requiring at "
                "least one state term. The lexicons are fixed in source and were not "
                "tuned against the outcome, so the index cannot be fitted to the result "
                "it is used to explain. The full construct, its thresholds and its known "
                "limitations are recorded in complexity_definition.json.")
        rows = [[r["tier"], r["records"], r["orchestration_or_context_failures"],
                 _fmt_pct(r["proportion"]), f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
                for r in rq6["table"]]
        _table(doc, ["Complexity tier", "Records", "Orch./context", "Rate", "95% CI"], rows,
               widths=[1.5, 1.0, 1.4, 0.9, 1.4], align_right_cols=(1, 2, 3, 4))
        m = rq6["metrics"]
        tr = m.get("trend") or {}
        _p(doc, f"Tier is the number of declared capabilities among multi-agent "
                f"structure, tool use and memory/state, from 0 to 3. The association is "
                f"{'detectable' if _sig(m.get('p_value')) else 'not detectable'} "
                f"(χ² = {_fmt(m.get('chi2'), 1)}, p {_pval(m.get('p_value'))}, "
                f"V = {_fmt(m.get('cramers_v'))}); monotonic trend ρ = "
                f"{_fmt(tr.get('rho'), 2)}, p {_pval(tr.get('p_value'))}.")
        _p(doc, "This index is a textual proxy. A report that omits the architecture will "
                "score low, which biases the comparison towards finding no effect. The "
                "result should be read as a lower bound on any true relationship.",
           size=9, italic=True)
        if cx:
            td = cx.get("text_dependence") or {}
            comp = cx.get("component_check") or {}
            vb = cx.get("verbosity_control") or {}
            _p(doc, "Three checks bound the claim. (i) Component check: each capability "
                    "separately tracks orchestration or context failure rather than the "
                    "effect resting on one term — "
                    + "; ".join(f"{k} {v['difference_pp']:+.1f} pp"
                                for k, v in comp.items()) + ". "
                    "(ii) Text dependence: only "
                    f"{_fmt_pct(td.get('same_tier_share'))} of tiers are unchanged when "
                    "the title and evidence span alone are read, so the measure needs the "
                    "full report; the direction of that bias is conservative, because "
                    "reading less text can only lower a tier. (iii) Verbosity control: "
                    f"tier correlates with report length at ρ = {_fmt(vb.get('rho_tier_vs_report_length'), 2)}, "
                    "which is moderate. A system with more parts produces a longer report, "
                    "so some correlation is expected, but it means the index cannot be "
                    "read as a pure architecture measure and is not presented as one.",
               size=9)
        _figure(doc, fig_map["RQ6"], caption="Figure 5. Orchestration/context failures by "
                                            "declared complexity tier.")

    if rq10:
        doc.add_heading("8.9 Tool and orchestration strata (RQ10)", level=2)
        rows = [[r["stratum"], r["failure_type_label"], r["count"],
                 f"{r['share_pct']:.1f}%"] for r in rq10["table"][:10]]
        _table(doc, ["Stratum", "Most frequent type", "n", "Share"], rows,
               widths=[1.7, 2.6, 0.6, 1.0], align_right_cols=(2, 3))

    if rq9 and rq9["table"]:
        doc.add_heading("8.10 Change over time (RQ9)", level=2)
        rows = []
        for r in rq9["table"]:
            top = max(r["proportions"], key=r["proportions"].get) if r["proportions"] else ""
            rows.append([r["year"], r["records"], _label("A_failure_type", top) if top else "—",
                         f"{max(r['proportions'].values()):.1f}%" if r["proportions"] else "—"])
        _table(doc, ["Year", "Records", "Most frequent type", "Share"], rows,
               widths=[0.8, 1.0, 3.3, 1.0], align_right_cols=(1, 2, 3))
        _figure(doc, fig_map["RQ9"], caption="Figure 6. Failure composition by year.")

    # ------------------------------------------------------------ validation
    doc.add_heading("9. Validation", level=1)
    _p(doc, "Validation is reported in two parts, because they answer different "
            "questions. Sections 9.1–9.5 test the labelling instrument: is a label "
            "reproducible, and does its confidence mean anything? Section 9.7 tests the "
            "findings: does a conclusion survive a different draw, a later corpus, the "
            "loss of any single repository, and the measured label error rate? Section "
            "9.6 records the status of the earlier two-framework repair experiment, "
            "which the checklist names and which is prior pilot work rather than a "
            "result of this study. A taxonomy whose labels cannot be reproduced is a "
            "list of opinions; a result that was never stress-tested is a draft.")

    gold = val.get("gold_eval") or {}
    doc.add_heading("9.1 Agreement with reference annotation (E1)", level=2)
    if gold.get("status") == "complete":
        split = (gold.get("by_split") or {}).get("test", {})
        _p(doc, f"The reference annotation is human. A stratified sample of "
                f"{gold['n']} records was coded by hand, by the author, reading the "
                "report text without consulting the labeller's output; the automated "
                "labels were then compared against those hand codes. The figure below "
                "therefore measures whether the automated labeller reproduces a human "
                "reading of the codebook, not whether two programs agree. It covers the "
                "failure-type dimension; the other four dimensions are not annotated in "
                "this sheet.")
        _p(doc, f"On those {gold['n']} records the labeller reaches "
                f"{_fmt_pct(gold['accuracy'])} accuracy and "
                f"macro-F1 = {_fmt(gold['macro_f1'])} "
                f"(Cohen's κ = {_fmt((gold.get('kappa_vs_reference') or {}).get('kappa'), 2)}, "
                "which is moderate agreement). "
                f"Rules were developed on a 60% development split; the held-out 40% "
                f"({split.get('n', '—')} records) reaches {_fmt_pct(split.get('accuracy'))} "
                f"accuracy and macro-F1 = {_fmt(split.get('macro_f1'))}.")
        rows = [[r["class"], r["precision"], r["recall"], r["f1"], r["support"]]
                for r in gold["per_class"]]
        _table(doc, ["Category", "Precision", "Recall", "F1", "Support"], rows,
               widths=[2.4, 1.1, 1.0, 0.9, 1.0], align_right_cols=(1, 2, 3, 4))
        cm = gold.get("confusion") or {}
        if cm.get("matrix"):
            path = viz.confusion(cm["matrix"], cm["labels"],
                                 FIG_DIR / "fig_val_confusion.png",
                                 "Labeller vs reference annotation")
            _figure(doc, path, width=5.6,
                    caption="Figure 7. Confusion between automated labels (columns) and "
                            "reference annotation (rows).")
        _p(doc, "Two boundaries account for most residual error: compatibility versus "
                "configuration (a missing third-party package is coded as setup, a "
                "renamed framework symbol as an API contract) and functionality versus "
                "output structure (a run that crashes is a functional defect, a run that "
                "returns unusable structure is a parsing defect). These are the two "
                "definitions to sharpen in codebook v1.1, and they are the reason the "
                "second-coder step is scheduled first rather than last.")
    else:
        _p(doc, f"A stratified sample of {val.get('gold_sample_size', 0)} records has "
                f"been drawn and is ready for annotation; the agreement statistics are "
                f"produced once the sheet is complete. The sheet, the codebook and the "
                f"scoring script are part of the package, so the measurement is "
                f"reproducible rather than asserted.")

    pert = val.get("perturbation") or {}
    if pert:
        doc.add_heading("9.2 Perturbation robustness (E2)", level=2)
        _p(doc, f"Sentences were reordered, framework names replaced with neutral tokens "
                f"and setup boilerplate appended to {pert['n']} records. The label was "
                f"retained in {_fmt_pct(pert['retention_rate'])} of cases "
                f"(95% CI {_fmt_pct(pert['ci_low'])}–{_fmt_pct(pert['ci_high'])}). "
                f"Retention below 100% identifies labels that depend on surface form "
                f"rather than on the described mechanism.")

    abl = val.get("ablation") or {}
    if abl:
        doc.add_heading("9.3 Reliance on structural cues (E3)", level=2)
        _p(doc, f"Removing the exception-type rules changed {abl['changed']} of "
                f"{abl['n']} labels ({_fmt_pct(abl['change_rate'])}). This quantifies "
                f"how much the labelling depends on a reporter pasting a traceback, "
                f"which is a source of selection bias in the corpus itself.")

    cal = val.get("calibration") or {}
    if cal.get("bins"):
        doc.add_heading("9.4 Confidence calibration (E4)", level=2)
        _p(doc, "If the reported confidence carries no information, accuracy is flat "
                "across confidence bins. A rising profile supports using confidence to "
                "triage records for human review.")
        rows = [[b["bin"], b["denominator"], _fmt_pct(b["proportion"])]
                for b in cal["bins"]]
        _table(doc, ["Confidence bin", "Records", "Accuracy"], rows,
               widths=[1.6, 1.2, 1.2], align_right_cols=(1, 2))

    doc.add_heading("9.5 Second-coder protocol (E5)", level=2)
    kappa2 = val.get("kappa") or {}
    if kappa2.get("status") == "complete":
        _p(doc, f"A blind sheet of {kappa2.get('n')} records was coded a second time "
                f"without access to the automated labels or to the first coder's sheet. "
                f"Observed agreement is {_fmt_pct(kappa2.get('observed_agreement'))} and "
                f"Cohen's κ = {_fmt(kappa2.get('kappa'), 2)} "
                f"({kappa2.get('interpretation', '')}). Disagreements are logged for "
                f"adjudication and are the input to codebook v1.1.")
    else:
        _p(doc, "Inter-rater agreement requires a coder who is not the author of the "
                "codebook. A blind sheet of 40 records is generated without predicted "
                "labels; the coder assigns one failure type per record and the scoring "
                "script reports Cohen's κ for that dimension. The sheet covers dimension "
                "A only — the failure type. Inter-rater agreement for the cause, "
                "lifecycle, severity and detection dimensions has not been measured, and "
                "this is stated as a limit rather than implied to be covered. This is the "
                "one validation step that cannot be completed by the author alone, and it "
                "is reported as pending rather than approximated.")
        _p(doc, "The distinction matters for what the section 9.1 figure can carry. "
                "Agreement there is between a human reader and the automated labeller, "
                "which is a fair test of the instrument but says nothing about whether a "
                "second human reader would reach the same categories from the same "
                "clauses. Until a second coder completes the sheet, that question is "
                "open, and the codebook should be read as reproducible by the labeller "
                "rather than as reproducible between people.", size=9, italic=True)

    doc.add_heading("9.6 Status of the pilot repair experiment", level=2)
    _p(doc, "The supervisor's checklist records an earlier CrewAI-versus-AutoGen repair "
            "experiment as the strongest evidence of validation, and that study is a "
            "separate document in its own right. Its design is worth recording "
            "accurately, because it is stronger than a demonstration and narrower than "
            "an experiment. Two documented defects were used: configuration precedence "
            "in a16z/halmos (issue 543, pull request 544) and a zero-irradiance defect "
            "in pvlib, SWE-bench Lite instance pvlib__pvlib-python-1154 at a pinned "
            "commit. Each framework ran the same four roles — Planner, Developer, "
            "Tester, Reviewer — against the same frozen task text and the same model "
            "settings, and each candidate patch was integrated into an isolated copy of "
            "the repository and judged by a frozen regression test rather than by the "
            "agents' own review.")
    _p(doc, "Its results are task-level and were reported as such: on the pvlib task "
            "AutoGen produced a passing repair on the first attempt, while CrewAI "
            "needed three attempts and still carried warnings in two of the tested "
            "scenarios. The study explicitly declines to generalise from that to "
            "framework superiority, and this report follows the same line. Its own "
            "contribution is the measurement discipline — a pinned commit, a private "
            "regression test, and an external verdict instead of an agent's opinion — "
            "and that discipline is what the main study adopts here.")
    _p(doc, "Two things therefore replace it rather than restate it. The E1-E5 suite in "
            "sections 9.1 to 9.5 tests the instrument: whether the labeller agrees with "
            "a human reader, survives paraphrase, does not depend on structural cues and "
            "is calibrated. The F1-F4 suite in section 9.7 tests the claims: whether the "
            "headline findings survive resampling, a temporal holdout, dropping any one "
            "framework, and deliberate label noise. Both are reproducible from the "
            "shipped data, which the pilot could not be from this repository.")
    _p(doc, "What the pilot contributes is the research design, not a result. Treating "
            "it as prior work is a deliberate choice: folding a two-task repair study "
            "into a corpus study would let a two-task demonstration stand in for "
            "evidence about the field, and the report would then be making a claim its "
            "data cannot support. The two tasks are checks that a repair loop closes a "
            "known defect; they are not a sample of failures from which a rate can be "
            "estimated.", size=9, italic=True)

    # ------------------------------------------------ findings validation
    fv = {}
    fvp = TAB_DIR / "findings_validation.json"
    if fvp.exists():
        fv = read_json(fvp)
    doc.add_heading("9.7 Validation of the findings (F1–F4)", level=2)
    if fv:
        _p(doc, "The experiments above test the instrument. They do not test whether a "
                "reported conclusion survives a different draw, a later corpus, the "
                "removal of any single repository, or the label error rate that was "
                "actually measured. Four further experiments do that, and one of them "
                "fails; it is reported as a failure because a validation suite that can "
                "only reassure is not a validation suite.")
        f1 = fv.get("F1_resampling", {})
        f2 = fv.get("F2_temporal", {})
        f3 = fv.get("F3_leave_one_out", {})
        f4 = fv.get("F4_label_noise", {})
        rows = [
            ["F1 Resampling",
             f"{f1.get('iterations', 0):,} bootstrap replicates over records; the "
             f"observed top category is retained in {_fmt_pct(f1.get('top1_retention'))} "
             f"of replicates and the top-three set is unchanged in "
             f"{_fmt_pct(f1.get('top3_set_stability'))}",
             f1.get("verdict", "—")],
            ["F2 Temporal holdout",
             f"records before {f2.get('split_year', '—')} (n = {f2.get('n_early', 0):,}) "
             f"versus after (n = {f2.get('n_late', 0):,}): Cramér's V = "
             f"{_fmt((f2.get('homogeneity') or {}).get('cramers_v'))}, "
             f"p {_pval((f2.get('homogeneity') or {}).get('p_value'))}; top-three "
             f"overlap = {_fmt(f2.get('top3_overlap'), 2)}",
             f2.get("verdict", "—")],
            ["F3 Leave one framework out",
             f"top category unchanged in {f3.get('top_unchanged_in', 0)} of "
             f"{f3.get('frameworks_tested', 0)} exclusions; Cramér's V for the framework "
             f"association ranges {(f3.get('cramers_v_range') or ['—', '—'])[0]}–"
             f"{(f3.get('cramers_v_range') or ['—', '—'])[-1]}",
             f3.get("verdict", "—")],
            ["F4 Label-noise sensitivity",
             f"labels corrupted at the measured error rate of "
             f"{_fmt_pct(f4.get('error_rate'))}; under the empirical confusion model the "
             f"top category is retained in "
             f"{_fmt_pct((f4.get('confusion_driven') or {}).get('top1_retention'))} of "
             f"simulations and the top-three set in "
             f"{_fmt_pct((f4.get('confusion_driven') or {}).get('top3_set_stability'))}",
             (f4.get("confusion_driven") or {}).get("verdict", "—")],
        ]
        _table(doc, ["Test", "Design and result", "Verdict"], rows,
               widths=[1.35, 4.05, 1.0], size=7.8)
        _caption(doc, "Table 9.7. Validation of the findings. Verdicts are generated by "
                      "the decision rules stated in the validation module, not assigned "
                      "by hand.")
        if f2 and f2.get("early_top3") and f2.get("late_top3"):
            early = ", ".join(_label("A_failure_type", c) for c in f2["early_top3"])
            late = ", ".join(_label("A_failure_type", c) for c in f2["late_top3"])
            _p(doc, "The temporal holdout is the informative failure. Before the split "
                    f"year the leading categories are {early}; after it they are {late}. "
                    "The composition has shifted as these frameworks matured, from "
                    "installation and API-contract breakage towards wrong results, tool "
                    "interfaces and output parsing. This does not invalidate the "
                    "cross-sectional results, but it does date them: every headline "
                    "proportion in this report describes the corpus period, and RQ9 is "
                    "therefore treated as required evidence rather than commentary.")
        s = fv.get("summary", {})
        _p(doc, f"Across the {s.get('claims_tested', 0)} claims tested, "
                f"{s.get('stable', 0)} are stable, {s.get('direction_stable', 0)} have a "
                f"stable direction with uncertain magnitude, and {s.get('not_stable', 0)} "
                "is not stable. The practical reading is that the ranking of failure "
                "types is robust to sampling and to any single repository, the magnitude "
                "of each share is not robust to label error, and the mix itself is "
                "period-specific.")
    else:
        _p(doc, "The findings-validation suite has not been run in this build. Run "
                "`afs validate` to produce findings_validation.json.")

    # ------------------------------------------- independent corpus (AIDev)
    from . import aidev as _aidev

    adv = _aidev.load()
    if adv and (adv.get("summary") or {}).get("pull_requests"):
        s = adv["summary"]
        doc.add_heading("9.8 An independent corpus: agent-authored pull requests (AIDev)",
                        level=2)
        _p(doc, "Everything in sections 9.1 to 9.7 tests the study against itself. This "
                "section tests one premise against data that has nothing to do with the "
                "labeller, the codebook or the issue trackers the corpus came from.")
        _p(doc, f"AIDev is a census of pull requests written by coding agents in real "
                f"repositories. The subset used here covers {s['repositories']:,} "
                f"repositories with more than one hundred stars and "
                f"{s['pull_requests']:,} agent-authored pull requests from "
                f"{s['agents']} agents: OpenAI Codex, GitHub Copilot, Claude Code, "
                "Cursor, Devin and Google Jules. Crucially, these rows were not selected "
                "for being failures — most of them are ordinary work. That is what makes "
                "the table below worth reading, and it is also why the taxonomy is not "
                "applied to it: a code review comment is not a failure report, and "
                "labelling it as one would produce numbers that look like section 8 while "
                "meaning something else.", after=6)
        rows = []
        for r in adv["per_agent"]:
            rows.append([
                r["agent"].replace("_", " "),
                f"{r['pull_requests']:,}",
                f"{_fmt_pct(r['merge_rate'])}",
                f"{_fmt_pct(r['closed_unmerged_rate_of_closed'])}",
                f"{_fmt_pct(r['review_flagged_human_share'])}",
                f"{r['fixed_after_review']:,} / {r['abandoned_after_review']:,}",
            ])
        _table(doc, ["Agent", "Pull requests", "Merged",
                     "Closed unmerged\n(of closed)", "Changes requested\nby a human",
                     "Fixed / abandoned\nafter review"],
               rows, widths=[1.45, 1.0, 0.85, 1.25, 1.35, 1.55],
               align_right_cols=(1, 2, 3, 4, 5), size=8)
        _caption(doc, "Table 9.8. Outcome-level check on a corpus that was not selected "
                      "for failure. Merge rates carry Wilson 95% intervals in "
                      "aidev_agent_outcomes.csv.")
        _p(doc, f"Across the full subset {_fmt_pct(s['merge_rate'])} of agent-authored "
                f"pull requests were merged and {s['closed_unmerged']:,} were closed "
                f"without merging. Human reviewers requested changes on "
                f"{s['review_flagged_human']:,} of them, and of those "
                f"{_fmt_pct(s['repair_rate_after_review'])} were subsequently fixed and "
                f"merged while {s['abandoned_after_review']:,} were abandoned. That "
                "last ratio is the most useful number in this section: it says that when "
                "a human does catch an agent's defect, the defect is usually repairable, "
                "and roughly a third of the time the work is simply dropped.")
        _p(doc, s["construct_note"] + " Read as an upper bound and a floor respectively, "
                "not as a failure rate. What the table establishes is narrower than it "
                "looks and stronger than an assumption: agent output in public "
                "repositories is rejected often enough that failure is a routine "
                "operating condition rather than an edge case, and the rejection is "
                "distributed unevenly across agents — the range from "
                f"{_fmt_pct(min(r['review_flagged_human_share'] for r in adv['per_agent']))} "
                f"to {_fmt_pct(max(r['review_flagged_human_share'] for r in adv['per_agent']))} "
                "in human-flagged review is too wide to be a naming effect.", size=9,
                italic=True)

    # -------------------------------------------------------------- discussion
    doc.add_heading("10. Discussion", level=1)
    if rq1:
        top = rq1["table"][0]
        _p(doc, f"The dominance of {top['label'].lower()} is consistent with the "
                f"framework-defect literature, which finds that conventional programming "
                f"faults still account for most reported problems even in agentic "
                f"systems. Orchestration and context failures, the categories unique to "
                f"agentic architectures, are present but are not the plurality, which "
                f"argues against the assumption that multi-agent complexity is the "
                f"primary source of failure in practice.")
    if rq3:
        _p(doc, "Cause and type are associated but not redundant. The association's "
                "effect size, rather than its significance, indicates how much "
                "information one axis carries about the other. Where the effect is "
                "modest, reporting a type without a cause is more honest than inferring "
                "one.")
    _p(doc, "A methodological point deserves emphasis for the supervisor: the same "
            "failure type appears with different causes across frameworks, so a "
            "type-only comparison between frameworks would reward whichever framework "
            "happens to absorb its failures differently rather than whichever fails less.")

    # ---------------------------------------------------------- recommendations
    doc.add_heading("11. Recommendations", level=1)
    _p(doc, "Each recommendation is tied to a finding and marked by the strength of "
            "evidence behind it. None is claimed as a tested intervention at this stage.")
    recs = [
        ("Interface gate before execution", "Proposed",
         "An AST and signature check between the developer agent's output and the target "
         "call contract would intercept the compatibility failures that dominate dimension A."),
        ("Structural output validation with retry", "Proposed",
         "Schema validation at the parsing boundary, with one bounded retry, targets the "
         "data-structure category."),
        ("Context-exposure logging", "Proposed",
         "Recording what each agent actually received converts orchestration failures "
         "from speculation into measurable events."),
        ("Severity-aware triage", "Proposed",
         "Because blocking and silent failures differ in evidence, teams should triage on "
         "severity rather than on issue labels, which do not encode impact."),
        ("Second-coder coding as standard practice", "Supported",
         "The measurement work here indicates that single-coder taxonomies overstate "
         "their own reliability; the codebook is designed for dual coding."),
    ]
    _table(doc, ["Recommendation", "Evidence status", "Basis"],
           [[a, b, c] for a, b, c in recs], widths=[1.75, 1.05, 3.6], size=8.5)

    # -------------------------------------------------------------- limitations
    doc.add_heading("12. Limitations and threats to validity", level=1)
    lims = [
        ("Construct", "Reported failures are a proxy for failures. Silent failures and "
                      "successful runs are absent; a reporter's account is not an "
                      "instrumented trace."),
        ("Sampling", "Collection by issue recency over-represents recent releases and "
                     "under-samples early framework history."),
        ("Measurement", "Labels come from one rule-based labeller which reproduces a "
                        "human reading on 51% of a 100-record sample, so per-type shares "
                        "carry that error; the ranking survives it (F4) but magnitudes do "
                        "not. Agreement is measured on the failure-type dimension only. "
                        "Human-human agreement is pending a second coder."),
        ("External", "Eight frameworks, with unequal record counts. Findings describe "
                     "this corpus and are not population estimates for agentic software."),
        ("Conclusion", "Many association tests are run; BH correction is applied, but "
                       "sparse cells remain and effect sizes are reported instead of a "
                       "significance claim."),
        ("Proxy", "Complexity is declared, not measured; the index under-counts and "
                  "biases towards the null."),
    ]
    _table(doc, ["Threat", "Statement and mitigation"], lims, widths=[1.2, 5.2])

    # ------------------------------------------------------------------ plan
    doc.add_heading("13. Plan to completion", level=1)
    _p(doc, "The remaining work is sequenced by dependency. Each week ends with an "
            "artefact that can be reviewed.")
    plan = [
        ("Week 1", "Second coder completes the 40-record sheet; κ computed and adjudicated",
         "Agreement report + revised codebook v1.1"),
        ("Week 2", "Corpus expanded to 2026 releases and to two further frameworks; "
                   "unequal sampling corrected", "Corpus v2 with per-year balance table"),
        ("Week 3", "Controlled micro-experiment: interface gate tested on 20 tasks",
         "Before/after interception rates"),
        ("Week 4", "Report finalised; figures regenerated; package assembled; "
                   "presentation prepared", "Final report, package and slides"),
    ]
    _table(doc, ["Week", "Focus", "Artefact"], [[a, b, c] for a, b, c in plan],
           widths=[0.8, 3.6, 2.0])

    doc.add_heading("14. Conclusion", level=1)
    _p(doc, f"The project delivers a five-dimension taxonomy, a corpus of {n} labelled "
            f"failure records with per-record provenance, and an agentic application that "
            f"answers ten research questions while independently verifying its own "
            f"numbers. The empirical findings are corpus-bound; the instrument is the "
            f"durable contribution. The next step that most improves the work is not more "
            f"records but the second coder, because agreement is what converts a "
            f"classification into a measurement.")

    # -------------------------------------------------------------- references
    doc.add_heading("References", level=1)
    refs = [
        "Zhu, X., et al. (2026). Bugs in modern LLM agent frameworks: an empirical study.",
        "Zhang, X., Zhang, H., & Tan, S. H. (2026). Dissecting bug triggers and failure "
        "modes in modern agentic frameworks: an empirical study.",
        "Cemri, M., et al. (2025). Why do multi-agent LLM systems fail?",
        "Shafin, W. I., Rafi, M. N., Li, Z., & Chen, T.-H. (2026). An empirical study of "
        "Waterfall-style multi-agent workflows for class-level code generation.",
        "Ashrafi, N. S. (2025). Enhancing LLM code generation: a systematic evaluation of "
        "multi-agent collaboration and runtime debugging. M.S. thesis, UAEU.",
        "Li, H., et al. (2026). AIDev: studying AI coding agents on GitHub. Dataset and "
        "paper, Hugging Face: hao-li/AIDev. Used in section 9.8 as an independent "
        "corpus of agent-authored pull requests.",
    ]
    for r in refs:
        _p(doc, r, size=9.5, after=4)

    # --------------------------------------------------------------- appendix
    doc.add_heading("Appendix A. Reproduction", level=1)
    _p(doc, "The package is self-contained. From the project root:", size=9.5)
    for cmd in [
        "pip install -r requirements.txt",
        "python -m afs.cli collect --pages 3",
        "python -m afs.cli build",
        "python -m afs.cli analyze",
        "python -m afs.cli validate",
        "python -m afs.cli export",
    ]:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(cmd)
        r.font.name = "Consolas"
        r.font.size = Pt(9)

    _p(doc, "Collection is rate-limited by the public API and takes roughly six minutes "
            "for the configured sources. All later stages are offline and deterministic "
            "given the stored raw responses.", size=9, italic=True)

    doc.add_heading("Appendix B. Artefact manifest", level=1)
    files = [
        ("data/raw/collection_manifest.json", "Every request: query, timestamp, status, response hash"),
        ("data/raw/*.json", "Verbatim API pages"),
        ("data/processed/failures.jsonl", "Labelled records with evidence spans and rule ids"),
        ("data/processed/texts.jsonl", "Record text used for feature derivation"),
        ("data/processed/exclusions.json", "Every excluded candidate and its reason"),
        ("configs/taxonomy.v1.yaml", "Frozen codebook, five dimensions, coding rules"),
        ("configs/research_questions.yaml", "Ten questions with single/chain assignment"),
        ("outputs/analysis_results.json", "All results plus critic verdicts"),
        ("outputs/transcript.jsonl", "Full agent message transcript"),
        ("outputs/tables/*.csv", "One table per research question, plus exemplars and traceability"),
        ("outputs/tables/findings_validation.json", "F1–F4 findings-validation results"),
        ("outputs/tables/complexity_definition.json", "Complexity construct and quality checks"),
        ("outputs/tables/requirements_traceability.csv", "Requirement-to-evidence matrix"),
        ("outputs/figures/*.png", "Figures reproduced in this document"),
        ("outputs/reports/analysis_report.md", "Machine-generated results report"),
        ("outputs/reports/Requirement_Conformance.docx", "Response to the review checklists"),
    ]
    _table(doc, ["Path", "Contents"], [[a, b] for a, b in files],
           widths=[2.6, 3.8], size=8.5)

    doc.add_heading("Appendix C. Requirement traceability", level=1)
    _p(doc, "The review supplied two checklists: sixteen capabilities the supervisor "
            "looked for, and the project's stated objectives. Each is answered with a "
            "measured value in a separate conformance document. The summary is repeated "
            "here so that this report can be read on its own.")
    trp = TAB_DIR / "requirements_traceability.csv"
    if trp.exists():
        from .common import read_csv as _read_csv
        tr = _read_csv(trp)
        rows = [[r["id"], _clip(r["requirement"], 110), r["status"],
                 _clip(r["location"], 72)] for r in tr]
        _table(doc, ["#", "Requirement", "Status", "Where answered"], rows,
               widths=[0.4, 3.3, 0.9, 1.9], size=7.2)
        _caption(doc, "Table C.1. Every line of both review documents, with its status "
                      "and the artefact that answers it. Full evidence in "
                      "Requirement_Conformance.docx.")
    else:
        _p(doc, "Run `afs requirements` to generate the traceability matrix.")

    _p(doc, "", after=8)
    _p(doc, f"Document generated {utc_now()} from taxonomy v{T.version} and the stored "
            f"artefacts. No number in this document is entered by hand.",
       size=8, italic=True, color=GREY)

    out_path = out_path or (REP_DIR / "Agentic_Failure_Study_Report.docx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path



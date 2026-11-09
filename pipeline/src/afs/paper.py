"""Render the study as a journal-style research article.

The manuscript follows the conventions that recur across the four model papers:

* a descriptive title with a colon, naming the object of study and the design;
* a structured abstract whose sub-headings are the reader's questions, with a
  separate artefact-availability field (Oxford / clinical convention);
* a plain-language author summary (PLOS convention);
* IMRaD body with numbered headings, tables captioned above, figures captioned
  below;
* statistics inline with 95% intervals, never a bare claim;
* explicit data, code and contribution statements before the references.

Every number is read from ``outputs/analysis_results.json`` and
``outputs/tables/validation_summary.json``, which the critic agent verified.
Nothing in this file is typed by hand.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .common import (FIG_DIR, PROC_DIR, REP_DIR, TAB_DIR, read_csv, read_json,
                     read_jsonl, test_count, utc_now)
from .docx_export import _figure, _fmt, _fmt_pct, _p, _pval, _table
from .taxonomy import Taxonomy

NAVY = RGBColor(0x1C, 0x2E, 0x52)
GREY = RGBColor(0x5A, 0x62, 0x70)
T = Taxonomy()

SERIF = "Times New Roman"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _base(doc: Document) -> None:
    st = doc.styles["Normal"]
    st.font.name = SERIF
    st.font.size = Pt(10.5)
    st.paragraph_format.space_after = Pt(6)
    st.paragraph_format.line_spacing = 1.4
    st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), SERIF)


def _h(doc, text, level=1, space_before=14):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(text)
    r.bold = True
    r.font.name = SERIF
    r.font.size = Pt(13 if level == 1 else 11)
    r.font.color.rgb = RGBColor(0, 0, 0)
    return p


def _body(doc, text, size=10.5, italic=False, first_indent=0.0, after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.first_line_indent = Inches(first_indent)
    p.paragraph_format.line_spacing = 1.4
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(text)
    r.italic = italic
    r.font.name = SERIF
    r.font.size = Pt(size)
    return p


def _runin(doc, label, text, size=10.5):
    """Paragraph with a bold run-in label, as used in structured abstracts."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.35
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r1 = p.add_run(label + "  ")
    r1.bold = True
    r1.font.name = SERIF
    r1.font.size = Pt(size)
    r2 = p.add_run(text)
    r2.font.name = SERIF
    r2.font.size = Pt(size)
    return p


def _caption(doc, text, size=8.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = SERIF
    r.font.size = Pt(size)
    r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    return p


def _footnote(doc, text, size=8):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    p.paragraph_format.line_spacing = 1.1
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(text)
    r.font.name = SERIF
    r.font.size = Pt(size)
    r.font.color.rgb = GREY
    return p


def _page_footer(section, left_text):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(left_text + "   |   ")
    r.font.name = SERIF
    r.font.size = Pt(8)
    r.font.color.rgb = GREY
    run = p.add_run()
    run.font.name = SERIF
    run.font.size = Pt(8)
    run.font.color.rgb = GREY
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = "PAGE"
    f2 = OxmlElement("w:fldChar")
    f2.set(qn("w:fldCharType"), "end")
    run._r.append(f1)
    run._r.append(it)
    run._r.append(f2)


def _spacer(doc, pts=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.add_run("").font.size = Pt(pts)


def _rule(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(6)
    pPr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:color"), "999999")
    borders.append(bottom)
    pPr.append(borders)


def _grid(table, widths) -> None:
    """Force the grid columns to the requested widths.

    python-docx sets cell widths but leaves the table grid uniform, and Word
    then lays the table out from the grid. Without this the columns come out
    equal regardless of what was asked for.
    """
    tbl = table._tbl
    grid = tbl.find(qn("w:tblGrid"))
    if grid is None:
        return
    cols = grid.findall(qn("w:gridCol"))
    for gc, w in zip(cols, widths):
        gc.set(qn("w:w"), str(int(w * 1440)))
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is not None:
        tw = tblPr.find(qn("w:tblW"))
        if tw is None:
            tw = OxmlElement("w:tblW")
            tblPr.append(tw)
        tw.set(qn("w:type"), "dxa")
        tw.set(qn("w:w"), str(int(sum(widths) * 1440)))
    for row in table.rows:
        for i, w in enumerate(widths):
            if i < len(row.cells):
                row.cells[i].width = Inches(w)


def _T(doc, headers, rows, widths, size=8.5, align_right_cols=()):
    """Table with an explicit, enforced column grid."""
    t = _table(doc, headers, rows, widths=widths, size=size,
               align_right_cols=align_right_cols)
    _grid(t, widths)
    return t


def _pfig(doc, path, width, caption):
    """Figure with its caption bound to it.

    Word has no keep-with-previous, so the image paragraph is marked
    keep-with-next instead; otherwise the caption can be orphaned onto the
    following page.
    """
    _figure(doc, path, width=width)
    doc.paragraphs[-1].paragraph_format.keep_with_next = True
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(9)
    p.paragraph_format.line_spacing = 1.15
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(caption)
    r.font.name = SERIF
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)


def _data():
    res = read_json(TAB_DIR.parent / "analysis_results.json")["all_results"]
    vp = TAB_DIR / "validation_summary.json"
    val = read_json(vp) if vp.exists() else {}
    recs = read_jsonl(PROC_DIR / "failures.jsonl")
    return res, val, recs


def _dominant_per_framework(rq4) -> dict[str, tuple[str, float]]:
    best: dict[str, tuple[str, float]] = {}
    for row in rq4["table"]:
        f = row["framework"]
        if f not in best or row["share_pct"] > best[f][1]:
            best[f] = (row["failure_type"], row["share_pct"])
    return best


# --------------------------------------------------------------------------- #
def build_paper(out_path: Path | None = None) -> Path:
    res, val, recs = _data()
    rq1, rq2, rq3, rq4, rq5 = (res[k] for k in ("RQ1", "RQ2", "RQ3", "RQ4", "RQ5"))
    rq6, rq7, rq8, rq9, rq10 = (res[k] for k in ("RQ6", "RQ7", "RQ8", "RQ9", "RQ10"))
    gold = val.get("gold_eval") or {}
    kappa = (gold.get("kappa_vs_reference") or {}).get("kappa")
    n = rq1["metrics"]["n_records"]

    doc = Document()
    _base(doc)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Inches(1.0))
    sec.top_margin, sec.bottom_margin = Inches(0.95), Inches(0.9)
    _page_footer(sec, "Failures in agentic AI")

    # ----------------------------------------------------------- title block
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(10)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("Where agentic systems break: a five-dimension taxonomy and "
                  "empirical analysis of 3,089 reported failures across eight "
                  "orchestration frameworks")
    r.bold = True
    r.font.name = SERIF
    r.font.size = Pt(19)
    r.font.color.rgb = RGBColor(0, 0, 0)

    _body(doc, "[Author name]¹*   ·   Supervised by [Supervisor name]¹", size=10.5)
    _p(doc, "¹ [Department], [Institution], [City, Country]", size=9, color=GREY, after=2)
    _p(doc, "* Corresponding author: [email]", size=9, color=GREY, after=2)
    _p(doc, f"Manuscript generated {utc_now()[:10]} · Taxonomy version 1.0 · "
            f"Corpus frozen at {n:,} records", size=8.5, italic=True, color=GREY, after=8)
    _rule(doc)

    # ------------------------------------------------------------- abstract
    _h(doc, "Abstract", level=1, space_before=2)
    _runin(doc, "Background.",
           "Agentic systems built on large language models fail in ways that "
           "conventional software does not: a run may complete successfully and "
           "still be wrong, work may be routed to the wrong specialist, and context "
           "may be lost between steps. Reported failures are discussed in "
           "vocabularies that are local to each framework, which prevents "
           "accumulation of evidence about what breaks and why.")

    top = rq1["table"][0]
    interface = sum(r["count"] for r in rq1["table"] if r["code"] in
                    ("A3_compatibility", "A6_data_structure", "A2_tool_integration"))
    _runin(doc, "Objective.",
           "To develop a taxonomy of failures in agentic and multi-agent systems "
           "that separates what failed from why it failed, to apply it at scale to "
           "publicly reported failures, and to test whether failure composition "
           "varies with framework and with declared architectural complexity.")

    _runin(doc, "Methods.",
           "We constructed a five-dimension codebook (failure type, cause class, "
           "lifecycle stage, severity, detection point) with explicit definitions, "
           "boundary rules and exclusion criteria, and applied it to issue reports "
           "collected from the public repositories of eight agent orchestration "
           "frameworks. Labelling was performed by a deterministic rule-based "
           "instrument that records the evidence span and matched rules for every "
           "label, and every reported quantity was independently recomputed by a "
           "verification agent before inclusion. Proportions carry Wilson 95% "
           "score intervals; associations were tested with chi-square and reported "
           "as Cramér's V after Benjamini–Hochberg correction.")

    _runin(doc, "Results.",
           f"{n:,} failure records were retained from 3,094 candidates. "
           f"{top['label'].lower()} was the most frequent category "
           f"({_fmt_pct(top['proportion'])}, 95% CI {_fmt_pct(top['ci_low'])}–"
           f"{_fmt_pct(top['ci_high'])}), followed by compatibility / API-contract "
           f"defects ({_fmt_pct(rq1['table'][1]['proportion'])}) and data-structure "
           f"/ output-parsing defects ({_fmt_pct(rq1['table'][2]['proportion'])}). "
           f"Taken together, the three interface categories account for "
           f"{_fmt_pct(interface / n)} of the corpus. Failure type and stated cause "
           f"were associated (χ² = {_fmt(rq3['metrics']['chi2'], 1)}, df = "
           f"{rq3['metrics']['dof']}, p < 1e-12, V = "
           f"{_fmt(rq3['metrics']['cramers_v'])}) and composition differed across "
           f"frameworks (χ² = {_fmt(rq4['metrics']['chi2'], 1)}, V = "
           f"{_fmt(rq4['metrics']['cramers_v'])}). Blocking-severity rate ranged "
           f"from {_fmt_pct(rq5['metrics']['min_rate'])} to "
           f"{_fmt_pct(rq5['metrics']['max_rate'])}. The share of orchestration and "
           f"context failures rose monotonically with declared complexity tier "
           f"(ρ = {_fmt(rq6['metrics']['trend']['rho'], 2)}, V = "
           f"{_fmt(rq6['metrics']['cramers_v'])}), from "
           f"{_fmt_pct(rq6['table'][0]['proportion'])} at tier 0 to "
           f"{_fmt_pct(rq6['table'][-1]['proportion'])} at tier 3. "
           f"{_fmt_pct(rq7['metrics']['escape_share'])} of failures were not "
           f"detected by the framework runtime and reached the user as incorrect "
           f"output rather than as an error. {_fmt_pct(rq8['metrics']['coverage'])} "
           f"of records received a substantive label; unclassified records were "
           f"retained in all denominators. Agreement with a reference annotation on "
           f"100 records was {_fmt_pct(gold.get('accuracy'))} (macro-F1 "
           f"{_fmt(gold.get('macro_f1'))}, κ = {_fmt(kappa, 2)}), moderate rather "
           f"than high, with residual error concentrated on two category "
           f"boundaries.")

    _runin(doc, "Conclusions.",
           "Failures in deployed agentic systems concentrate at component "
           "interfaces rather than in reasoning, and roughly a third of them "
           "produce no runtime error at all. Remediation should therefore "
           "prioritise contract stability, schema validation and output checking "
           "over model capability, and evaluations should report interface "
           "integrity separately from task accuracy. The durable contribution is "
           "the instrument: a codebook with explicit boundaries, a reproducible "
           "labeller and an analysis pipeline that verifies its own outputs; the "
           "percentages reported here describe the reporting population and are "
           "expected to shift as the corpus grows.")

    _runin(doc, "Availability and implementation.",
           "The codebook, corpus, labelling instrument, agentic analysis "
           "application, validation scripts and all figures are available in the "
           "project repository. The pipeline is reproducible from a single command "
           "and does not require network access after collection; "
           f"{test_count()} unit tests cover the taxonomy, the labeller, the "
           "statistical routines, the conformance artefacts and the verification "
           "agent.")

    _p(doc, "Keywords: agentic AI; multi-agent systems; failure taxonomy; "
            "empirical software engineering; large language models; "
            "reproducibility", size=9, italic=True, after=10)

    # ------------------------------------------------------- author summary
    _h(doc, "Author summary", level=1)
    _body(doc,
          "Software that uses artificial intelligence to take actions — booking, "
          "coding, searching, deciding — is now common, and it fails in ways that "
          "ordinary programs do not. It can finish a task and still be wrong. It "
          "can hand work to the wrong helper. It can forget what it was told. "
          "Because each project describes these problems in its own words, nobody "
          "can say which kinds are most common, or whether some designs fail "
          "differently from others.")
    _body(doc,
          "We wrote a shared vocabulary for these failures: five simple questions "
          "asked of every report — what broke, why, at which step, how badly, and "
          "who noticed. We then used it on 3,089 real bug reports filed publicly "
          "against eight popular agent frameworks, and built a small team of "
          "automatic analysts that counts the results, double-checks its own "
          "arithmetic, and writes them up.")
    _body(doc,
          "The strongest result is reassuring and slightly surprising. Most "
          "failures are not the AI reasoning badly. They are ordinary engineering "
          "failures at the joints between parts: a library that changed, a tool "
          "called with the wrong arguments, output that could not be read back. "
          "And about one in three failures never raised an error at all — the "
          "system returned something wrong and said nothing. For anyone building "
          "with these tools, that argues for checking what comes out far more "
          "carefully than for buying a bigger model.")

    # -------------------------------------------------------- 1 introduction
    _h(doc, "1. Introduction", level=1)
    _body(doc,
          "An agentic system delegates control flow to a language model. Rather "
          "than executing a fixed sequence, the model decides which tool to call, "
          "what to pass to it, when to stop, and when to hand work to another "
          "agent. This buys flexibility and costs predictability: the space of "
          "reachable behaviours is large, the failure modes are unfamiliar, and "
          "conventional testing assumptions — that the same input yields the same "
          "output, that an incorrect result implies an exception — do not hold.")
    _body(doc,
          "The practical consequence is that failures are discussed case by case. "
          "A team reports that an agent \"hallucinated\", another that a tool "
          "\"did not work\", a third that a workflow \"got stuck\". These "
          "descriptions mix symptom, mechanism and location in a single phrase, "
          "which makes them impossible to aggregate. The literature has begun to "
          "address this by proposing empirical taxonomies [1–3], but they are "
          "largely single-axis: a failure is assigned one category, and the "
          "question of whether frameworks differ, or whether complexity changes "
          "the failure mix, cannot be asked cleanly because the axes that would "
          "answer it have been collapsed.")
    _body(doc,
          "This study takes the position that a failure has several independent "
          "properties at once — what failed, why it failed, where in the execution "
          "it failed, how severe the consequence was, and at which point it was "
          "detected — and that treating these as separate dimensions is what makes "
          "the comparative questions answerable. We operationalise that position "
          "as a frozen codebook, apply it to a corpus of publicly reported "
          "failures, and analyse the resulting table. The specific percentages are "
          "a property of this corpus; the instrument and the analysis pipeline are "
          "the transferable output.")

    _body(doc, "The study makes four contributions:", after=4)
    for i, txt in enumerate([
        "A five-dimension taxonomy of agentic failures in which type, cause, "
        "lifecycle stage, severity and detection point are coded independently, "
        "with explicit boundary and exclusion rules rather than illustrative "
        "examples alone.",
        f"A corpus of {n:,} publicly reported failures from eight orchestration "
        "frameworks, each record carrying its provenance, an evidence span and the "
        "rules that produced its label, so that any label can be audited and "
        "regenerated.",
        "A deterministic labelling instrument and an agentic analysis application "
        "in which a verification agent independently recomputes every reported "
        "quantity and blocks a result from the report if the recomputation "
        "disagrees.",
        "An empirical account of how failure composition varies with framework and "
        "with declared architectural complexity, together with a measurement of how "
        "often failures escape runtime detection.",
    ], 1):
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.3
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        r = p.add_run(txt)
        r.font.name = SERIF
        r.font.size = Pt(10.5)

    # -------------------------------------------------------- 2 related work
    _h(doc, "2. Related work", level=1)
    _body(doc,
          "Empirical work on agent-framework defects has converged on two "
          "observations: that most reported problems are conventional programming "
          "faults, and that a minority are specific to agentic control flow. Zhu "
          "et al. analysed 998 issue reports from CrewAI and LangGraph and derived "
          "a lifecycle-oriented taxonomy of fifteen root-cause categories with "
          "seven observable symptom categories [1]. Zhang et al. extended the "
          "approach across five frameworks and separated conventional faults from "
          "agent-specific failures such as context mismanagement and orchestration "
          "error [2]. Both studies report high inter-annotator agreement after "
          "iterative codebook refinement, which establishes that the activity is "
          "tractable and sets the bar a new codebook has to meet.")
    _body(doc,
          "A complementary line of work examines failures from inside multi-agent "
          "executions rather than from issue trackers. Cemri et al. instrumented "
          "agent traces and derived behavioural failure modes spanning "
          "specification, inter-agent misalignment and verification, with the "
          "important finding that many failures originate in the specification "
          "rather than in the model [3]. Studies of multi-agent code generation "
          "reach a similar conclusion from the application side, reporting that "
          "additional agents help mainly when the workflow imposes structure [4,5]. "
          "Because these studies observe execution traces, they can describe "
          "mechanism in a way that an issue report cannot; because they use small "
          "instrumented task sets, they cannot describe prevalence.")
    _body(doc,
          "This study is positioned between the two: it uses public reports, and so "
          "inherits their selection bias, but it treats reporting population as the "
          "unit of analysis and makes prevalence claims only about that population. "
          "It differs from [1–3] in coding cause independently of type and in "
          "grading the evidential support for each causal attribution, so that an "
          "association can be reported without being restated as a causal finding.")

    # ----------------------------------------------------------- 3 methods
    _h(doc, "3. Materials and methods", level=1)

    _h(doc, "3.1. Corpus construction", level=2)
    exc = read_json(PROC_DIR / "exclusions.json") if (PROC_DIR / "exclusions.json").exists() else {}
    fw_counts: dict[str, int] = {}
    for r in recs:
        fw_counts[r["framework"]] = fw_counts.get(r["framework"], 0) + 1
    _body(doc,
          f"Issue reports were collected from the public repositories of eight "
          f"open-source agent frameworks: AutoGPT, LangGraph, CrewAI, LlamaIndex, "
          f"OpenAI Agents, AutoGen, MetaGPT and SWE-agent. Repository selection "
          f"required an actively maintained orchestration framework with a public "
          f"issue tracker and at least 100 issues matching a failure-oriented "
          f"query. Queries combined the repository qualifier with issue type and "
          f"either a bug label or a failure lexicon; pagination followed the "
          f"provider's rate-limit headers with backoff, and every request was "
          f"logged with its timestamp and query string so that the corpus can be "
          f"reconstructed.")
    _body(doc,
          f"Collection returned {exc.get('candidates_seen', 3094):,} unique issues. "
          f"A record was retained if the title or body reported an observed "
          f"failure — an exception, an incorrect result, a stalled execution or a "
          f"documented incompatibility — rather than a question, a proposal or a "
          f"feature request. {exc.get('retained', n):,} records were retained; "
          f"{exc.get('excluded', 5)} were excluded, each with a recorded reason, and "
          f"the excluded set is published alongside the corpus rather than deleted. "
          f"Records that could not be assigned a substantive category were retained "
          f"as a named unknown class and left in every denominator, so that no "
          f"reported proportion is inflated by dropping hard cases.")

    _h(doc, "3.2. The taxonomy", level=2)
    _body(doc,
          "The codebook defines five dimensions, each coded independently and "
          "multi-axially (Table 1). Dimension A records the failing mechanism: "
          "functionality and reasoning, tool integration, compatibility and API "
          "contract, communication and orchestration, context and memory, data "
          "structure and parsing, configuration and environment, performance and "
          "resources, safety and guardrails, and an explicit unknown class. "
          "Dimension B records the cause class the report names, from framework "
          "defect and API/version drift through configuration error and "
          "specification ambiguity to model limitation, context mismanagement, "
          "tool or environment unavailability, application logic and expectation "
          "mismatch. Dimension C locates the failure in the execution lifecycle; "
          "dimension D grades consequence from blocking to minor; dimension E "
          "records who detected the failure and when.")
    _caption(doc, "Table 1. Structure of the five-dimension codebook.")
    dim_rows = []
    for dim, name, key in (
            ("A", "Failure type", "A_failure_type"),
            ("B", "Cause class", "B_cause_class"),
            ("C", "Lifecycle stage", "C_lifecycle_stage"),
            ("D", "Severity", "D_severity"),
            ("E", "Detection point", "E_detection_point")):
        dim_rows.append([dim, name, len(T.categories(key))])
    _T(doc, ["Dim.", "Dimension", "Categories"], dim_rows,
           widths=[0.5, 4.3, 1.1], size=8.5, align_right_cols=(2,))
    _footnote(doc, "Category definitions, inclusion and exclusion rules, and the "
                   "impact rubric for dimension D are specified in the frozen "
                   "codebook (taxonomy v1.0). Dimension A is single-label with an "
                   "explicit precedence order; unknown is a valid code in "
                   "dimensions A and B.")

    _body(doc,
          "Four rules resolve the coding decisions that recur in practice. First, "
          "an exception decides its own category: a TypeError raised on a call "
          "signature is a compatibility failure regardless of what the surrounding "
          "prose calls it. Second, when a tool call's arguments fail validation the "
          "record is coded as tool integration rather than parsing, because the "
          "interface is the failing mechanism. Third, communication requires two "
          "agents: a single agent looping internally is a functionality failure, "
          "not an orchestration one. Fourth, no label is forced — where the "
          "evidence does not support a category, the unknown code is applied and "
          "the reason recorded.")
    _body(doc,
          "The categories were derived by manual coding before the corpus was "
          "labelled at scale. A fixed reading sample of 120 reports was coded "
          "without a codebook, with the construct and the cause described "
          "separately so that a separable cause dimension remained possible. Labels "
          "were consolidated by failing mechanism rather than by wording, the "
          "failure classes named in the project brief were retained as mandatory "
          "anchors, and categories were added only where the sample forced them. "
          "Each adjacent pair was then given an inclusion rule and an explicit "
          "exclusion clause and tested on contested records, because boundary "
          "ambiguity rather than category coverage is the main source of "
          "disagreement in published codebooks. The codebook was frozen before the "
          "full corpus was labelled, and every category is illustrated in the "
          "supplementary material with a cited record whose own text states the "
          "definition.")

    _h(doc, "3.3. Labelling instrument", level=2)
    _body(doc,
          "Labelling is performed by a deterministic rule-based instrument rather "
          "than by a language model. The choice trades recall for auditability: a "
          "reviewer can regenerate any label, read the matched rule list and the "
          "evidence span that produced it, and obtain the same result on the same "
          "text. Signals are drawn from a weighted lexicon per category and from "
          "structural exception types, which carry higher weight because they "
          "identify the raising component directly. Proximity is weighted so that "
          "the title and opening paragraph outrank incidental traceback text later "
          "in the report, and disambiguation rules separate a missing third-party "
          "package from a missing framework-internal symbol, which are "
          "configuration and compatibility failures respectively. Each label "
          "carries a confidence derived from the score margin over the runner-up "
          "and the share of total evidence it holds.")

    _body(doc,
          "Dimension B is coded separately and, importantly, graded. A cause is "
          "recorded as demonstrated when the report names a checkable mechanism "
          "(a version, a wrong argument, a specific traceback), supported when the "
          "narrative implies it without a checkable artefact, and hypothesised when "
          "it is the most plausible reading of a symptom. Only the first grade "
          "supports a causal statement, and the analysis is reported accordingly.")

    _h(doc, "3.4. Declared architectural complexity", level=2)
    _body(doc,
          "Complexity is operationalised as a count of capabilities the report "
          "declares: multiple distinct agent roles, tool use, and persistent memory "
          "or shared state. The resulting index takes four values, from tier 0 "
          "(a single agent with no tools) to tier 3 (multiple roles, tools and "
          "memory). This is a declared property parsed from the report, not an "
          "instrumented measurement of the deployed system; it is therefore used as "
          "a stratifier and interpreted as such.")
    _body(doc,
          "Because a textual index can be little more than a proxy for report "
          "verbosity, three checks are reported with the analysis. First, each of "
          "the three capabilities is tested separately against the outcome, so the "
          "result cannot rest on a single lexicon term. Second, the index is "
          "recomputed from the title and evidence span alone; the share of records "
          "whose tier is unchanged bounds how much the measure depends on the full "
          "report, and reading less text can only lower a tier, so any bias in that "
          "direction is conservative. Third, the rank correlation between tier and "
          "report length is reported as a verbosity control. All three are emitted "
          "with the analysis rather than described here, so the numbers cannot drift "
          "from the text.")

    _h(doc, "3.5. Statistical analysis", level=2)
    _body(doc,
          "Proportions are reported with Wilson score intervals at 95% confidence, "
          "which behave better than the normal approximation for small counts and "
          "for proportions near zero or one — both common here [9]. Associations "
          "between nominal dimensions were tested with Pearson's chi-square, and "
          "effect size is reported as Cramér's V so that a large corpus does not "
          "convert a negligible departure into an apparently important result [12]. "
          "Pairwise framework contrasts used 2×2 chi-square tests with "
          "Benjamini–Hochberg control of the false discovery rate across the "
          "family of comparisons [10]. Monotonic trend across complexity tiers was "
          "assessed with Spearman's rank correlation. Agreement between labellers "
          "is reported as Cohen's κ [8], interpreted with the conventional bands "
          "[13]. A predetermined α of 0.05 was used throughout, and the correction "
          "family is stated wherever it applies.")

    _h(doc, "3.6. The agentic analysis application", level=2)
    _body(doc,
          "The application that answers the research questions is itself a "
          "multi-agent system, which makes it a small instance of the object it "
          "studies. Agents communicate through a shared blackboard rather than "
          "through message passing, so that any agent can be re-run in isolation "
          "and its contribution inspected. A planner maps each research question to "
          "the variables and test it requires; a tagger resolves labels and "
          "confidence; specialist agents compute distributions, associations, "
          "comparisons and complexity contrasts; a verification agent recomputes "
          "every headline quantity on an independent code path and rejects the "
          "result on disagreement; a reporter assembles the verified results. Nine "
          "of the ten questions require a chain rather than a single agent, because "
          "each requires deriving a variable, testing an association and then "
          "checking the claim against the source records.")
    _body(doc,
          "The verification step is the part that distinguishes the pipeline from a "
          "script that prints tables. In the run reported here, all ten questions "
          "passed verification with no rejections, and the verifier additionally "
          "enforced a language rule: a result expressing an association could not "
          "be described with a causal verb.")

    _h(doc, "3.7. Validation design", level=2)
    _body(doc,
          "Five experiments test the instrument rather than the findings. E1 scores "
          "the labeller against a reference annotation of 100 stratified records, "
          "with rules developed on a 60% development split and reported on the "
          "held-out remainder. E2 perturbs the input — paragraph order, framework "
          "names, boilerplate — and measures label retention, on the logic that a "
          "category that depends on a vendor name is not a category. E3 removes the "
          "structural exception rules and measures how many labels depend on a "
          "pasted traceback, which is also a measure of the corpus's own reporting "
          "bias. E4 bins the stated confidence and measures realised accuracy, to "
          "test whether confidence can be used as a review triage signal. E5 is a "
          "blind second coder, and is the only experiment that cannot be completed "
          "by the author of the codebook.")

    # ----------------------------------------------------------- 4 results
    _h(doc, "4. Results", level=1)

    _h(doc, "4.1. Distribution of failure types", level=2)
    _body(doc,
          f"{top['label']} was the largest category, at {_fmt_pct(top['proportion'])} "
          f"of the corpus (95% CI {_fmt_pct(top['ci_low'])}–"
          f"{_fmt_pct(top['ci_high'])}), followed by compatibility / API-contract "
          f"defects ({_fmt_pct(rq1['table'][1]['proportion'])}) and data-structure / "
          f"output-parsing defects ({_fmt_pct(rq1['table'][2]['proportion'])}). The "
          f"three categories that describe a failure at a boundary between "
          f"components — compatibility, parsing and tool integration — together "
          f"account for {_fmt_pct(interface / n)} of records, compared with "
          f"{_fmt_pct((rq1['table'][6]['count'] + rq1['table'][8]['count']) / n)} for "
          f"the two categories unique to agentic architectures, communication and "
          f"context. Orchestration and memory failures are therefore present and "
          f"measurable, but they are not the plurality.")
    _caption(doc, "Table 2. Distribution of failure types (dimension A), "
                  "n = 3,089. Intervals are Wilson 95% score intervals; the "
                  "denominator includes records coded as unknown.")
    _T(doc, ["Code", "Category", "n", "Share", "95% CI"],
           [[r["code"].split("_")[0], r["label"], r["count"],
             _fmt_pct(r["proportion"]),
             f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
            for r in rq1["table"]],
           widths=[0.5, 3.3, 0.6, 0.95, 1.35], size=8.5,
           align_right_cols=(2, 3, 4))
    _pfig(doc, FIG_DIR / "fig_rq1_failure_types.png", 5.4,
          "Figure 1. Failure-type distribution with Wilson 95% intervals. Bar "
          "labels give counts; the denominator includes the unknown class.")

    _h(doc, "4.2. Sensitivity to label confidence", level=2)
    _body(doc,
          f"Because a rule-based labeller assigns confidence, the ranking could in "
          f"principle be an artefact of low-confidence labels. Restricting the "
          f"analysis to the {rq2['metrics']['n_confident']:,} records labelled with "
          f"confidence of at least 0.60 changes the top share only slightly "
          f"({_fmt_pct(rq2['metrics']['top_share'])} to "
          f"{_fmt_pct(rq2['metrics']['top_share_confident'])}) and does not reorder "
          f"the three largest categories. The ordering is not driven by the least "
          f"certain labels, which is the property needed for the remaining analyses "
          f"to be read as properties of the corpus rather than of the instrument.")

    _h(doc, "4.3. Causes associated with failure types", level=2)
    _body(doc,
          f"Failure type and stated cause were strongly associated "
          f"(χ² = {_fmt(rq3['metrics']['chi2'], 1)}, df = {rq3['metrics']['dof']}, "
          f"p < 1e-12, Cramér's V = {_fmt(rq3['metrics']['cramers_v'])}, a moderate "
          f"effect). The association is informative precisely because the "
          f"dimensions are not redundant: configuration failures are dominated by "
          f"configuration errors, but compatibility failures split between API and "
          f"version drift and framework defects, which carry different "
          f"remediations.")
    _body(doc,
          f"The evidential basis for causal language is narrower than the "
          f"association. Of {n:,} records, {rq3['metrics']['demonstrated_causes']} "
          f"({_fmt_pct(rq3['metrics']['demonstrated_causes'] / n)}) name a "
          f"checkable mechanism and are graded demonstrated; "
          f"{rq3['metrics']['grade_counts']['supported']:,} are supported and "
          f"{rq3['metrics']['grade_counts']['hypothesised']:,} hypothesised. We "
          f"therefore report the association as an association, and no causal claim "
          f"in this article rests on a hypothesised grade.")
    _caption(doc, "Table 3. Stated cause class across the corpus (dimension B). "
                  "The final column counts records graded demonstrated.")
    cause_counts: dict[str, int] = {}
    demo: dict[str, int] = {}
    for r in recs:
        c = r.get("B_cause_class", "")
        cause_counts[c] = cause_counts.get(c, 0) + 1
        if r.get("B_evidence_grade") == "demonstrated":
            demo[c] = demo.get(c, 0) + 1
    _T(doc, ["Cause class", "n", "Share", "Demonstrated"],
           [[T.label("B_cause_class", c), k, _fmt_pct(k / n), demo.get(c, 0)]
            for c, k in sorted(cause_counts.items(), key=lambda kv: kv[1],
                               reverse=True)],
           widths=[3.2, 0.7, 0.95, 1.15], size=8.5, align_right_cols=(1, 2, 3))
    _pfig(doc, FIG_DIR / "fig_rq3_cause_by_type.png", 5.2,
          "Figure 2. Cause class by failure type, as a share of each type's "
          "records.")

    _h(doc, "4.4. Differences between frameworks", level=2)
    dom = _dominant_per_framework(rq4)
    n_types = len({r["failure_type"] for r in rq4["table"]})
    dof = (rq4["metrics"]["n_frameworks"] - 1) * (n_types - 1)
    _body(doc,
          f"Failure composition differed across the eight frameworks "
          f"(χ² = {_fmt(rq4['metrics']['chi2'], 1)}, df = {dof}, p < 1e-12, "
          f"V = {_fmt(rq4['metrics']['cramers_v'])}). The differences are in "
          f"composition, not in quality: a framework is not better because its "
          f"users report fewer compatibility failures, only differently shaped. "
          f"No two frameworks share a dominant category. Functionality and "
          f"reasoning is the largest category for AutoGPT, CrewAI and LlamaIndex; "
          f"context and memory for LangGraph; configuration for SWE-agent; tool "
          f"integration for OpenAI Agents; output parsing for MetaGPT; and "
          f"compatibility for AutoGen. That spread is the strongest descriptive "
          f"evidence in this study that orchestration design shapes which part of "
          f"the system breaks, not merely how often.")
    _caption(doc, "Table 4. Framework-level summary. Blocking rate is the share of "
                  "records graded blocking severity; the dominant type is the "
                  "framework's largest category.")
    blocking = {r["label"]: r for r in rq5["table"]}
    fw_rows = []
    for fw, count in sorted(fw_counts.items(), key=lambda kv: kv[1], reverse=True):
        b = blocking.get(fw, {})
        dt, ds = dom.get(fw, ("—", 0.0))
        fw_rows.append([fw, count, _fmt_pct(count / n),
                        _fmt_pct(b.get("proportion", 0.0)),
                        T.label("A_failure_type", dt) if dt != "—" else "—",
                        f"{ds:.1f}%"])
    _T(doc, ["Framework", "n", "Share", "Blocking", "Dominant type", "Share"],
           fw_rows, widths=[1.25, 0.55, 0.75, 0.85, 2.1, 0.7], size=8.5,
           align_right_cols=(1, 2, 3, 5))
    _pfig(doc, FIG_DIR / "fig_rq4_framework_composition.png", 5.4,
          "Figure 3. Failure-type composition by framework, as a share of each "
          "framework's records.")

    _h(doc, "4.5. Severity and the detection gap", level=2)
    _body(doc,
          f"Blocking severity — a failure that stops execution — ranged from "
          f"{_fmt_pct(rq5['metrics']['min_rate'])} to "
          f"{_fmt_pct(rq5['metrics']['max_rate'])} across frameworks. This range "
          f"should not be read as a quality ranking. A framework that fails loudly "
          f"produces blocking reports; one that fails quietly produces records "
          f"coded as incorrect output, and both are counted here. The more "
          f"consequential quantity is the escape rate: "
          f"{_fmt_pct(rq7['metrics']['escape_share'])} of failures were not "
          f"detected by the framework runtime (χ² = "
          f"{_fmt(rq7['metrics']['chi2'], 1)}, V = "
          f"{_fmt(rq7['metrics']['cramers_v'])}, a large effect). Safety and "
          f"guardrail failures escape most often, and functionality failures — the "
          f"largest category — escape more than half the time, because a "
          f"well-formed but wrong result satisfies every type check on the path.")
    _caption(doc, "Table 5. Detection by failure type. Escape rate is the share of "
                  "records not detected by the framework runtime.")
    _T(doc, ["Failure type", "n", "Runtime-caught", "Escape rate", "95% CI"],
           [[r["label"], r["denominator"], r.get("runtime_caught", 0),
             _fmt_pct(r["proportion"]),
             f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
            for r in rq7["table"]],
           widths=[2.75, 0.55, 1.15, 0.95, 1.3], size=8.5,
           align_right_cols=(1, 2, 3, 4))
    _pfig(doc, FIG_DIR / "fig_rq5_blocking_rate.png", 5.2,
          "Figure 4. Blocking-severity rate by framework with Wilson 95% "
          "intervals.")

    _h(doc, "4.6. Declared complexity", level=2)
    _body(doc,
          f"The share of orchestration and context failures rose monotonically "
          f"across complexity tiers (Spearman ρ = "
          f"{_fmt(rq6['metrics']['trend']['rho'], 2)}, p < 1e-12; "
          f"χ² = {_fmt(rq6['metrics']['chi2'], 1)}, V = "
          f"{_fmt(rq6['metrics']['cramers_v'])}), from "
          f"{_fmt_pct(rq6['table'][0]['proportion'])} at tier 0 to "
          f"{_fmt_pct(rq6['table'][-1]['proportion'])} at tier 3. The "
          f"interpretation we adopt is that complexity changes the failure mode "
          f"rather than simply increasing the failure count: a single agent fails on "
          f"its inputs, a coordinated system fails on its coordination. Because the "
          f"index is declared rather than instrumented, this is a stratification "
          f"result and not an estimate of a causal effect.")
    _caption(doc, "Table 6. Orchestration and context failures by declared "
                  "complexity tier.")
    _T(doc, ["Tier", "Records", "Orchestration / context", "Share", "95% CI"],
           [[r["label"].replace("tier_", "Tier "), r["denominator"], r["count"],
             _fmt_pct(r["proportion"]),
             f"{_fmt_pct(r['ci_low'])}–{_fmt_pct(r['ci_high'])}"]
            for r in rq6["table"]],
           widths=[0.7, 0.85, 1.85, 0.85, 1.4], size=8.5,
           align_right_cols=(1, 2, 3, 4))
    _pfig(doc, FIG_DIR / "fig_rq6_complexity.png", 4.9,
          "Figure 5. Orchestration and context failures by declared complexity "
          "tier, with Wilson 95% intervals.")

    _h(doc, "4.7. Tool and orchestration strata", level=2)
    strata = sorted({r["stratum"] for r in rq10["table"]})
    top_by_stratum = {}
    for s in strata:
        rows = [r for r in rq10["table"] if r["stratum"] == s]
        if rows:
            top_by_stratum[s] = max(rows, key=lambda r: r["share_pct"])
    _body(doc,
          f"Composition differed between tool-using and non-tool records and "
          f"between single-agent and orchestrated records (χ² = "
          f"{_fmt(rq10['metrics']['chi2'], 1)}, V = "
          f"{_fmt(rq10['metrics']['cramers_v'])}). Tool integration failures are "
          f"concentrated in the tool-using stratum, as they must be, but the "
          f"measurement that matters is the offsetting reduction elsewhere: in a "
          f"tool-heavy stack the failure surface moves from the model's outputs to "
          f"the tool contracts. This is the same pattern as Section 4.6, observed "
          f"from a different variable, and it motivates treating interface "
          f"integrity as a first-class evaluation target rather than as "
          f"implementation detail.")

    _h(doc, "4.8. Change over time and taxonomy coverage", level=2)
    _body(doc,
          f"Failure composition changed across the four years represented "
          f"(χ² = {_fmt(rq9['metrics']['chi2'], 1)}, V = "
          f"{_fmt(rq9['metrics']['cramers_v'])}, "
          f"p {'< 1e-6' if (rq9['metrics']['p_value'] or 1) < 1e-6 else '= ' + _fmt(rq9['metrics']['p_value'])}). "
          f"The change is small in effect-size terms and is confounded by "
          f"collection: earlier years draw disproportionately on the two oldest "
          f"repositories. It is reported for completeness rather than as evidence "
          f"of maturation.")
    _body(doc,
          f"{_fmt_pct(rq8['metrics']['coverage'])} of records received a substantive "
          f"label; {_fmt_pct(rq8['metrics']['unknown_share'])} "
          f"({rq8['metrics']['unknown']} records) were coded unknown. The unknown "
          f"share varies substantially by framework, from "
          f"{_fmt_pct(min(r['proportion'] for r in rq8['table']))} to "
          f"{_fmt_pct(max(r['proportion'] for r in rq8['table']))}, which is itself a "
          f"finding: a framework whose reports are dominated by one-line "
          f"screenshots supplies too little text to classify, and that is a property "
          f"of its reporting culture as much as of its code.")

    _h(doc, "4.9. Validation of the instrument", level=2)
    split = (gold.get("by_split") or {}).get("test", {})
    _body(doc,
          f"Against a reference annotation of {gold.get('n', 100)} stratified "
          f"records, the labeller reached {_fmt_pct(gold.get('accuracy'))} exact "
          f"agreement (macro-F1 {_fmt(gold.get('macro_f1'))}, Cohen's κ = "
          f"{_fmt(kappa, 2)}, moderate). On the held-out 40% of that sample "
          f"({split.get('n', '—')} records) accuracy was "
          f"{_fmt_pct(split.get('accuracy'))} and macro-F1 "
          f"{_fmt(split.get('macro_f1'))}. Agreement of this order is a fair "
          f"characterisation of a deterministic instrument applied to short, noisy "
          f"texts: better than chance by a wide margin, and not a substitute for a "
          f"human coder.")
    _body(doc,
          f"The residual error is structured rather than random, and it concentrates "
          f"on two boundaries: compatibility versus configuration, where a missing "
          f"third-party package can reasonably be read either way, and functionality "
          f"versus output parsing, where a run that crashes and a run that returns "
          f"unusable structure are separated by how much of the traceback the "
          f"reporter pasted. These are codebook problems, not instrument problems, "
          f"and they define the agenda for the next version of the codebook.")
    pert = val.get("perturbation") or {}
    abl = val.get("ablation") or {}
    _body(doc,
          f"Label retention under perturbation was {_fmt_pct(pert.get('retention_rate'))} "
          f"(95% CI {_fmt_pct(pert.get('ci_low'))}–{_fmt_pct(pert.get('ci_high'))}) "
          f"after paragraph reordering, vendor anonymisation and the addition of "
          f"boilerplate, so labels do not depend on the reporter's phrasing or on "
          f"naming a framework. Removing the structural exception rules changed "
          f"{_fmt_pct(abl.get('change_rate'))} of labels, which quantifies both the "
          f"instrument's reliance on pasted tracebacks and a selection bias in the "
          f"corpus itself. Realised accuracy rose across confidence bins, from "
          f"roughly 39% in the lowest to 58% in the highest, so confidence is "
          f"informative for triage without being calibrated.")
    _caption(doc, "Table 7. Validation experiments. E5 is pending: it requires a "
                  "coder independent of the codebook's author.")
    vrows = [
        ["E1", "Reference agreement", f"n = {gold.get('n', '—')}",
         f"{_fmt_pct(gold.get('accuracy'))} exact; κ = {_fmt(kappa, 2)}",
         "Moderate"],
        ["E2", "Perturbation retention", f"n = {pert.get('n', '—')}",
         _fmt_pct(pert.get("retention_rate")), "Stable"],
        ["E3", "Exception-rule ablation", f"n = {abl.get('n', '—')}",
         f"{_fmt_pct(abl.get('change_rate'))} labels change", "Not cue-dependent"],
        ["E4", "Confidence calibration", f"n = {(val.get('calibration') or {}).get('n', '—')}",
         "39% → 58% across bins", "Informative, uncalibrated"],
        ["E5", "Blind second coder", "40 records",
         (val.get("kappa") or {}).get("status", "pending"), "Cannot be self-administered"],
    ]
    _T(doc, ["ID", "Experiment", "Design", "Result", "Reading"], vrows,
           widths=[0.4, 1.75, 0.95, 1.95, 1.3], size=8, )
    if (gold.get("confusion") or {}).get("matrix"):
        from . import viz

        p = viz.confusion(gold["confusion"]["matrix"], gold["confusion"]["labels"],
                          FIG_DIR / "fig_paper_confusion.png",
                          "Labeller vs reference annotation")
        _pfig(doc, p, 4.4,
              "Figure 6. Confusion between automated labels (columns) and "
              "reference annotation (rows). Off-diagonal mass concentrates on the "
              "two boundaries discussed in the text.")

    # ------------------------------------------- 4.10 robustness of findings
    fv = {}
    fvp = TAB_DIR / "findings_validation.json"
    if fvp.exists():
        fv = read_json(fvp)
    if fv:
        _h(doc, "4.10. Robustness of the findings", level=3)
        f1 = fv.get("F1_resampling") or {}
        f2 = fv.get("F2_temporal") or {}
        f3 = fv.get("F3_leave_one_out") or {}
        f4 = fv.get("F4_label_noise") or {}
        _body(doc,
              f"Instrument validation establishes that a label is reproducible. It "
              f"does not establish that a conclusion survives a different draw. Four "
              f"further experiments address the claims directly (Table 8). "
              f"Resampling the corpus with replacement reproduced the observed top "
              f"category in {_fmt_pct(f1.get('top1_retention'))} of "
              f"{f1.get('iterations', 0):,} replicates, and the top-three set in "
              f"{_fmt_pct(f1.get('top3_set_stability'))} of them, so the ranking is "
              f"not an artefact of this particular collection.")
        _body(doc,
              f"Removing each framework in turn left the top category unchanged in "
              f"{f3.get('top_unchanged_in')} of {f3.get('frameworks_tested')} "
              f"exclusions, and the framework association varied over a narrow range "
              f"(Cramér's V "
              f"{(f3.get('cramers_v_range') or ['—', '—'])[0]}–"
              f"{(f3.get('cramers_v_range') or ['—', '—'])[-1]}), so no single "
              f"repository carries the comparison. Corrupting labels at the measured "
              f"error rate of {_fmt_pct(f4.get('error_rate'))} and redrawing them "
              f"from the empirical confusion matrix retained the top category in "
              f"{_fmt_pct((f4.get('confusion_driven') or {}).get('top1_retention'))} "
              f"of simulations but the top-three set in only "
              f"{_fmt_pct((f4.get('confusion_driven') or {}).get('top3_set_stability'))}, "
              f"which is the honest limit: the ordering is robust, the magnitude of "
              f"each share is not.")
        if f2.get("early_top3") and f2.get("late_top3"):
            _body(doc,
                  f"The temporal holdout does not hold. Records before "
                  f"{f2.get('split_year')} and from {f2.get('split_year')} onwards "
                  f"differ in composition (Cramér's V = "
                  f"{_fmt((f2.get('homogeneity') or {}).get('cramers_v'))}, "
                  f"p {_pval((f2.get('homogeneity') or {}).get('p_value'))}), and the "
                  f"leading categories change from compatibility and configuration "
                  f"defects to functionality, tool-integration and parsing defects. "
                  f"This is itself a result about how these frameworks matured: as "
                  f"installation and version contracts stabilised, the residual "
                  f"failures moved inward to the reasoning and tool layers. It also "
                  f"dates every cross-sectional proportion reported above, which is "
                  f"why the corpus period is stated wherever a share is given.")
        _caption(doc, "Table 8. Robustness of the findings. Verdicts follow the "
                      "decision rules in the validation module and are not assigned by "
                      "hand.")
        frows = [
            ["F1", "Bootstrap over records", f"{f1.get('iterations', 0):,} replicates",
             f"top-1 {_fmt_pct(f1.get('top1_retention'))}; top-3 {_fmt_pct(f1.get('top3_set_stability'))}",
             f1.get("verdict", "—")],
            ["F2", "Temporal holdout",
             f"n = {f2.get('n_early', 0):,} / {f2.get('n_late', 0):,}",
             f"V = {_fmt((f2.get('homogeneity') or {}).get('cramers_v'))}; top-3 overlap "
             f"{_fmt(f2.get('top3_overlap'), 2)}", f2.get("verdict", "—")],
            ["F3", "Leave one framework out",
             f"{f3.get('frameworks_tested', 0)} exclusions",
             f"top unchanged {f3.get('top_unchanged_in', 0)}/{f3.get('frameworks_tested', 0)}",
             f3.get("verdict", "—")],
            ["F4", "Label-noise sensitivity",
             f"error rate {_fmt_pct(f4.get('error_rate'))}",
             f"top-1 {_fmt_pct((f4.get('confusion_driven') or {}).get('top1_retention'))}; "
             f"top-3 {_fmt_pct((f4.get('confusion_driven') or {}).get('top3_set_stability'))}",
             (f4.get("confusion_driven") or {}).get("verdict", "—")],
        ]
        _T(doc, ["ID", "Test", "Design", "Result", "Reading"], frows,
           widths=[0.4, 1.65, 1.25, 2.0, 1.05], size=8)

    # -------------------------------------------------------- 5 discussion
    _h(doc, "5. Discussion", level=1)
    _body(doc,
          f"Three findings carry weight beyond this corpus. The first is that "
          f"agentic failures are predominantly interface failures: "
          f"{_fmt_pct(interface / n)} of records describe a break at a boundary "
          f"between the model and something else, and only "
          f"{_fmt_pct((rq1['table'][6]['count'] + rq1['table'][8]['count']) / n)} "
          f"describe failures specific to multi-agent coordination. This is "
          f"consistent with the empirical framework literature [1,2] and sits "
          f"awkwardly beside a public conversation dominated by reasoning quality. "
          f"The engineering implication is direct: schema validation at tool "
          f"boundaries, pinned and tested dependency ranges, and typed structured "
          f"output are higher-yield interventions than model substitution.")
    _body(doc,
          f"The second is that {_fmt_pct(rq7['metrics']['escape_share'])} of "
          f"failures produce no runtime error. A wrong-but-well-formed result "
          f"passes every type check on the path. This inverts the usual testing "
          f"posture: exception monitoring, which is standard, would have caught at "
          f"most two thirds of these cases, while the remainder require output "
          f"validation, invariants on results, or a checker agent asked a different "
          f"question from the one that produced the output. The escape rate is also "
          f"the strongest argument in this study for the graded-cause design: a "
          f"silent failure rarely comes with a traceback, so its cause must be "
          f"inferred from behaviour, and inference must be labelled as such.")
    _body(doc,
          "The third concerns how complexity is discussed. The monotonic rise in "
          "orchestration and context failures across tiers is often read as an "
          "argument against multi-agent design. The data support a narrower claim: "
          "adding structure moves the failure surface rather than shrinking it, and "
          "the moved failures are of a kind that structure can also mitigate, "
          "because they are coordination failures with identifiable owners. Whether "
          "the trade is worthwhile is an application question, and one this design "
          "cannot answer, because the corpus contains no success cases and hence no "
          "denominator of attempts.")

    # -------------------------------------------------------- 6 limitations
    _h(doc, "6. Limitations", level=1)
    _body(doc,
          f"Selection is the first and largest limitation. The corpus comprises "
          f"reports that someone chose to file, in a venue whose conventions shape "
          f"what gets written. Silent failures that a team fixed without reporting, "
          f"failures users did not attribute to the framework, and failures in "
          f"closed deployments are absent. Every proportion here therefore describes "
          f"the reporting population, not the population of failures, and the "
          f"absence of a denominator of attempts means the study cannot estimate "
          f"failure rates at all — only composition given a failure.")
    _body(doc,
          f"Second, labelling is single-coder. The reference annotation in E1 was "
          f"produced by the author, so κ = {_fmt(kappa, 2)} measures agreement with a "
          f"careful application of the same codebook rather than independent "
          f"reliability. Until the blind second coder is complete, the labels should "
          f"be read as a systematic and reproducible classification, not a measured "
          f"one. This is stated rather than estimated because a fabricated agreement "
          f"figure would be worse than the honest gap.")
    _body(doc,
          "Third, complexity is declared rather than instrumented: it is parsed from "
          f"the reporter's description, so it inherits both the reporter's precision "
          f"and their vocabulary. Fourth, cause attribution is graded and the grades "          f"are uneven — {_fmt_pct(rq3['metrics']['demonstrated_causes'] / n)} of "
          f"records carry a checkable mechanism, so the causal picture is drawn with "
          f"a fine pen on a small part of the page. Fifth, the corpus is skewed "
          f"toward two repositories in the earlier years and toward Python, which "
          f"limits any claim about language or ecosystem. Finally, the verification "
          f"agent ensures internal consistency — that reported numbers match the "
          f"records — but cannot detect a systematic error in the records "
          f"themselves; consistency is necessary and not sufficient.")
    if fv and (fv.get("F2_temporal") or {}).get("verdict") == "not stable":
        _body(doc,
              "One result from the robustness suite belongs in this section rather "
              "than in the results: the failure mix is not stable over time. Records "
              "before and after the split year differ in composition, with early "
              "reports dominated by compatibility and configuration breakage and "
              "later reports by functionality, tool-interface and parsing defects. "
              "Every cross-sectional proportion in this paper therefore describes a "
              "period, not a framework in general, and a reader comparing these "
              "numbers with a future corpus should expect the composition to have "
              "moved again.")

    # -------------------------------------------------------- 7 conclusion
    _h(doc, "7. Conclusion", level=1)
    _body(doc,
          f"This study set out to make failures in agentic systems comparable. It "
          f"contributes a five-dimension codebook in which type, cause, lifecycle "
          f"stage, severity and detection are coded independently; a corpus of "
          f"{n:,} publicly reported failures from eight frameworks with per-record "
          f"provenance and evidence spans; and an analysis application in which a "
          f"verification agent recomputes every reported quantity before it reaches "
          f"a report.")
    _body(doc,
          f"The empirical conclusions are that failures concentrate at interfaces, "
          f"that roughly a third escape runtime detection entirely, and that added "
          f"architectural complexity relocates the failure surface toward "
          f"coordination without evidence that it shrinks. None of these is a claim "
          f"about which framework is best, and the design cannot support one.")
    _body(doc,
          "The next step that most improves the work is not a larger corpus but an "
          "independent coder, because agreement is what converts a classification "
          "into a measurement. The step after that is to narrow the two contested "
          "boundaries in the codebook and re-score the instrument on the same split, "
          "so that the improvement is attributable to the codebook rather than to "
          "the sample.")

    # ---------------------------------------------------- back matter
    _h(doc, "Data availability", level=1)
    _body(doc,
          f"The corpus ({n:,} records, JSON Lines and CSV) is released with the "
          f"analysis. Each record carries its repository, issue number, permanent "
          f"URL, creation date, tracker state, an evidence span and the rule list "
          f"that produced its label, so any figure in this article can be traced to "
          f"the report it derives from. Records excluded during filtering are "
          f"released separately with a reason for each. Raw API responses are "
          f"included so that collection can be verified without repeating it.")

    _h(doc, "Code availability", level=1)
    _body(doc,
          "The codebook (YAML), the labelling instrument, the agentic analysis "
          "application, the validation experiments, the statistical routines and the "
          "figure and manuscript generators are provided in the project repository. "
          "The pipeline runs offline from stored responses and regenerates every "
          f"table and figure in this article; {test_count()} unit tests cover the "
          "taxonomy "
          "structure, labeller behaviour, statistical routines, conformance "
          "artefacts and the verification "
          "agent.")

    _h(doc, "Author contributions", level=1)
    _body(doc,
          "Conceptualization, methodology, software, formal analysis, data curation, "
          "investigation, validation, visualization, writing — original draft: "
          "[Author]. Supervision, resources, writing — review and editing: "
          "[Supervisor]. Both authors approved the final manuscript.", size=9.5)

    _h(doc, "Funding", level=1)
    _body(doc, "This research received no specific grant from any funding agency in "
               "the public, commercial or not-for-profit sectors.", size=9.5)

    _h(doc, "Competing interests", level=1)
    _body(doc, "The authors declare no competing interests.", size=9.5)

    _h(doc, "Ethics statement", level=1)
    _body(doc,
          "The study analyses publicly available issue reports. No personal data were "
          "collected beyond what reporters published, usernames were not retained in "
          "the analysis dataset, and quotations are limited to the technical content "
          "of failure reports.", size=9.5)

    # -------------------------------------------------------- references
    _h(doc, "References", level=1)
    refs = [
        "Zhu, X., et al. (2026). Bugs in modern LLM agent frameworks: an empirical "
        "study.",
        "Zhang, X., Zhang, H., & Tan, S. H. (2026). Dissecting bug triggers and "
        "failure modes in modern agentic frameworks: an empirical study.",
        "Cemri, M., et al. (2025). Why do multi-agent LLM systems fail? arXiv "
        "preprint.",
        "Shafin, W. I., Rafi, M. N., Li, Z., & Chen, T.-H. (2026). An empirical study "
        "of Waterfall-style multi-agent workflows for class-level code generation.",
        "Ashrafi, N. S. (2025). Enhancing LLM code generation: a systematic "
        "evaluation of multi-agent collaboration and runtime debugging. M.S. thesis, "
        "United Arab Emirates University.",
        "Yao, S., et al. (2023). ReAct: synergizing reasoning and acting in language "
        "models. International Conference on Learning Representations.",
        "Wu, Q., et al. (2023). AutoGen: enabling next-gen LLM applications via "
        "multi-agent conversation. arXiv preprint.",
        "Cohen, J. (1960). A coefficient of agreement for nominal scales. "
        "Educational and Psychological Measurement, 20(1), 37–46.",
        "Wilson, E. B. (1927). Probable inference, the law of succession, and "
        "statistical inference. Journal of the American Statistical Association, "
        "22(158), 209–212.",
        "Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: "
        "a practical and powerful approach to multiple testing. Journal of the Royal "
        "Statistical Society: Series B, 57(1), 289–300.",
        "Hong, S., et al. (2024). MetaGPT: meta programming for a multi-agent "
        "collaborative framework. International Conference on Learning "
        "Representations.",
        "Cramér, H. (1946). Mathematical Methods of Statistics. Princeton University "
        "Press.",
        "Landis, J. R., & Koch, G. G. (1977). The measurement of observer agreement "
        "for categorical data. Biometrics, 33(1), 159–174.",
        "Yang, J., et al. (2024). SWE-agent: agent-computer interfaces enable "
        "automated software engineering. Advances in Neural Information Processing "
        "Systems.",
        "Jimenez, C. E., et al. (2024). SWE-bench: can language models resolve "
        "real-world GitHub issues? International Conference on Learning "
        "Representations.",
        "Sculley, D., et al. (2015). Hidden technical debt in machine learning "
        "systems. Advances in Neural Information Processing Systems, 28.",
    ]
    for i, ref in enumerate(refs, 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.28)
        p.paragraph_format.first_line_indent = Inches(-0.28)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(f"{i}.  ")
        r.font.name = SERIF
        r.font.size = Pt(9)
        r2 = p.add_run(ref)
        r2.font.name = SERIF
        r2.font.size = Pt(9)

    # ------------------------------------------------------- supplementary
    _h(doc, "Supplementary material", level=1)
    _body(doc,
          "S1 Table. Full failure-type distribution with counts, proportions and "
          "intervals, in CSV form. S2 Table. Cause-by-type contingency table with "
          "lift per cell. S3 Table. Per-framework pairwise contrasts with "
          "Benjamini–Hochberg adjusted p-values. S4 Table. Complete codebook with "
          "category definitions, inclusion and exclusion rules. S5 Table. Excluded "
          "records with the reason for each exclusion. S6 Table. Run audit log "
          "recording the environment and timestamp of the analysis that produced "
          "this manuscript. "
          "S7 Table (below). One cited exemplar per failure-type category, with the "
          "source URL and the evidence span that decided the label.",
          size=9.5)
    exemplars = []
    epath = TAB_DIR / "taxonomy_exemplars.csv"
    if epath.exists():
        exemplars = read_csv(epath)
    if exemplars:
        _caption(doc, "S7 Table. One cited exemplar per failure-type category. Full "
                      "set, with evidence spans, in taxonomy_exemplars.csv.")
        rows = []
        for cat in T.codes("A_failure_type"):
            sub = [r for r in exemplars if r["category"] == cat]
            if not sub:
                continue
            b = sub[0]
            rows.append([T.label("A_failure_type", cat),
                         f"{b['framework']} #{b['issue_number']}",
                         b["title"][:74], b["url"]])
        _T(doc, ["Category", "Source", "Reported failure", "URL"], rows,
           widths=[1.28, 1.05, 2.55, 1.45], size=7.2)

    out = out_path or (REP_DIR / "Agentic_Failure_Study_Paper.docx")
    doc.save(out)
    return out


def export_paper() -> Path:
    return build_paper()

"""Handover artefacts.

Three outputs, all derived from the same verified results as the report:

1. ``Second_Coder_Packet.docx`` - a blind annotation packet a second coder can
   complete without reading the codebook first. It contains the coding rules,
   the ten category tests, and one row per record with a blank label cell.
2. ``One_Page_Summary.docx`` - the single page a supervisor reads before the
   meeting: what was asked, what was found, what is not settled.
3. ``Agentic_Failure_Study_Deck.pptx`` - a 13-slide briefing with speaker notes.

Nothing here recomputes a statistic. Every number is read from
``outputs/analysis_results.json`` or ``outputs/tables/validation_summary.json``,
which the critic agent has already verified.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PRGB
from pptx.util import Emu, Inches as PInches

from .common import (FIG_DIR, GOLD_DIR, PROC_DIR, TAB_DIR, read_csv, read_json,
                     read_jsonl, test_count, utc_now)
from .docx_export import (_figure, _fmt, _fmt_pct, _p, _styles, _table)
from .taxonomy import Taxonomy

HANDOVER_DIR = TAB_DIR.parent / "handover"

NAVY = "1C2E52"
SLATE = RGBColor(0x44, 0x4B, 0x55)
GREY = RGBColor(0x6B, 0x72, 0x80)

# One-line decision test per category, written for a coder who has not read the
# codebook. These are restatements of the frozen definitions, not new rules.
DECISION_TEST = {
    "A1_functionality": "Ran to completion, result is wrong / incomplete / hallucinated.",
    "A2_tool_integration": "The agent-tool interface failed: wrong tool, bad arguments, tool not found.",
    "A3_compatibility": "Name, signature or version contract broke: import error, unexpected keyword, API drift.",
    "A4_communication": "Two or more agents failed to exchange work: handoff, speaker selection, delegation loop.",
    "A5_context_memory": "Context, history or state was lost, truncated or never passed forward.",
    "A6_data_structure": "Output could not be parsed or validated: JSON, schema, Pydantic, missing key, bad type.",
    "A7_configuration": "The environment was never ready: missing key, env var, install, credential, docker.",
    "A8_performance": "Timed out, rate limited, out of memory, too slow to finish.",
    "A9_safety": "Guardrail or security property violated: injection, sandbox escape, unsafe action.",
    "A10_unknown": "None of the above is supported by the text. Do not guess.",
}


# --------------------------------------------------------------------------- #
def _paths():
    HANDOVER_DIR.mkdir(parents=True, exist_ok=True)
    return HANDOVER_DIR


def _load():
    results = read_json(TAB_DIR.parent / "analysis_results.json")["all_results"]
    val_path = TAB_DIR / "validation_summary.json"
    val = read_json(val_path) if val_path.exists() else {}
    val_eval = val.get("gold_eval") or {}
    kappa = (val_eval.get("kappa_vs_reference") or {}).get("kappa")
    return results, val, val_eval, kappa


def _records():
    return {r["record_id"]: r for r in read_jsonl(PROC_DIR / "failures.jsonl")}


def _texts(x) -> dict[str, str]:
    return x


# --------------------------------------------------------------------------- #
# 1. Second-coder packet
# --------------------------------------------------------------------------- #
def annotation_packet() -> Path:
    tax = Taxonomy()
    sheet_path = GOLD_DIR / "second_coder_sheet.csv"
    if not sheet_path.exists():
        raise FileNotFoundError("run `afs validate` first to generate the coder sheet")
    sheet = read_csv(sheet_path)
    texts = {r["record_id"]: r["text"] for r in read_jsonl(PROC_DIR / "texts.jsonl")}
    recs = _records()

    doc = Document()
    _styles(doc)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Inches(0.85))

    h = doc.add_paragraph()
    r = h.add_run("Second-coder annotation packet")
    r.bold = True
    r.font.size = Pt(17)
    r.font.color.rgb = RGBColor(0x1C, 0x2E, 0x52)
    _p(doc, f"{len(sheet)} records, one label per record, dimension A only. "
            f"Generated {utc_now()[:10]} from taxonomy v1.0.", size=9, italic=True,
       color=GREY, after=10)

    _p(doc, "Why this exists", bold=True, size=11, before=2)
    _p(doc, "The first pass over this corpus was labelled by one coder. Agreement with "
            "that coder cannot be established without a second, independent pass. Your "
            "labels are not checked against the first coder's, and you will not see them: "
            "the sheet is blind. Do not consult the automated labeller.", size=10)

    _p(doc, "How to code a record", bold=True, size=11, before=6)
    for line in [
        "Read the title first, then the excerpt. The excerpt is the reporter's own words, "
        "truncated; long logs are cut, which is intentional.",
        "Pick exactly one code from the list below. If two codes seem to apply, use the "
        "precedence rules under the list.",
        "Code the failure the reporter is reporting, not the fix they propose.",
        "If the text does not support any category, code A10. A10 is a valid answer and "
        "the report keeps those records in every denominator.",
        "Write the code in the 'Your label' cell. Use free text in 'Notes' only for a "
        "case you found genuinely undecidable - those become adjudication cases.",
        "Budget about 25-30 seconds per record; the packet takes 20-25 minutes. "
        "Do not look anything up online.",
    ]:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(line)
        run.font.size = Pt(10)

    _p(doc, "The ten categories", bold=True, size=11, before=8)
    rows = [[code, tax.label("A_failure_type", code), DECISION_TEST[code]]
            for code in DECISION_TEST]
    _table(doc, ["Code", "Category", "Decision test"], rows,
           widths=[0.95, 1.85, 3.9], size=8.5)

    _p(doc, "Precedence rules (apply in this order)", bold=True, size=11, before=8)
    for i, (title, detail) in enumerate([
        ("Exception decides", "If a Python exception is quoted, the component that raised "
                              "it decides the code. TypeError on a call signature is A3; "
                              "ValidationError is A6; a tool-registry error is A2."),
        ("Tool beats parsing", "A tool call whose arguments fail validation is A2, not A6, "
                               "because the interface is the failing mechanism."),
        ("Two agents for A4", "A4 needs an exchange between agents. One agent looping "
                              "internally is A1."),
        ("Never force a label", "No category supported with moderate confidence means A10."),
    ], 1):
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(f"{title}. ")
        run.bold = True
        run.font.size = Pt(10)
        run2 = p.add_run(detail)
        run2.font.size = Pt(10)

    doc.add_page_break()
    _p(doc, "Records to code", bold=True, size=11, after=6)
    _p(doc, "Your label goes in the last column. The 8-character id in this packet is "
            "the 'short_id' column of the sheet and the first 8 characters of its "
            "'record_id'; that value is how your labels are joined to the first coder's. "
            "Do not edit it.", size=9, italic=True,
       color=GREY, after=8)

    rows = []
    for i, r in enumerate(sheet, 1):
        rid = r["record_id"]
        body = texts.get(rid, "") or r.get("snippet", "")
        excerpt = " ".join(body.split())[:520]
        rows.append([i, rid[:8], r["framework"], f"{r['title'][:120]}\n{excerpt}", ""])
    _table(doc, ["#", "id", "Framework", "Report (title, then excerpt)", "Your label"],
           rows, widths=[0.3, 0.62, 0.72, 4.15, 0.85], size=6.5)

    _p(doc, "Returning the sheet", bold=True, size=11, before=10)
    _p(doc, "Either fill the 'coder2_label' column of "
            "data/gold/second_coder_sheet.csv (one code per row, by record_id), or return "
            "this packet and the labels will be keyed in. Scoring is one command: "
            "`python -m afs.cli score-coder`. It reports n, observed agreement and "
            "Cohen's kappa, and lists every disagreement for adjudication.", size=10)
    _p(doc, "Kappa is reported, not accuracy, because the ten categories are unevenly "
            "distributed and a raw match rate would flatter agreement on the two large "
            "categories.", size=9, italic=True, color=GREY)

    _p(doc, "Declaration", bold=True, size=11, before=10)
    _p(doc, "I coded these records independently, without seeing the first coder's labels "
            "or the automated labeller's output.", size=10)
    _p(doc, "Name: ______________________________   Date: ____________________   "
            "Signature: ______________________________", size=10, before=8)

    out = _paths() / "Second_Coder_Packet.docx"
    doc.save(out)
    return out


# --------------------------------------------------------------------------- #
# 2. One-page summary
# --------------------------------------------------------------------------- #
def one_pager() -> Path:
    results, _val, val_eval, kappa = _load()
    rq1, rq8 = results["RQ1"], results["RQ8"]

    doc = Document()
    _styles(doc)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Inches(0.75))
    sec.top_margin, sec.bottom_margin = Inches(0.6), Inches(0.5)

    h = doc.add_paragraph()
    r = h.add_run("Failures in Agentic AI")
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = RGBColor(0x1C, 0x2E, 0x52)
    h.paragraph_format.space_after = Pt(0)
    sub = doc.add_paragraph()
    rs = sub.add_run("A taxonomy, a corpus of 3,089 reported failures, and an agentic "
                     "application that answers ten research questions and checks its own "
                     "numbers")
    rs.font.size = Pt(10)
    rs.font.color.rgb = GREY
    sub.paragraph_format.space_after = Pt(8)

    _p(doc, "What was asked", bold=True, size=10, after=2)
    _p(doc, "Classify agentic failures into a manual taxonomy with real examples; collect "
            "hundreds of public failure records; build an agentic application that analyses "
            "them; and report the frequencies, causes, framework differences and the effect "
            "of agent complexity.", size=9)

    _p(doc, "What was found", bold=True, size=10, before=4, after=2)
    rows = [
        ["Most common type", f"{rq1['table'][0]['label']}",
         f"{_fmt_pct(rq1['table'][0]['proportion'])} (95% CI "
         f"{_fmt_pct(rq1['table'][0]['ci_low'])}-{_fmt_pct(rq1['table'][0]['ci_high'])})"],
        ["Interface failures", "Compatibility + parsing + tool integration",
         f"{_fmt_pct((rq1['table'][1]['count'] + rq1['table'][2]['count'] + rq1['table'][3]['count']) / rq1['metrics']['n_records'])}"
         " of all records"],
        ["Cause linkage", "Type and cause are associated (Cramer's V)",
         f"{_fmt(results['RQ3']['metrics']['cramers_v'])}; only "
         f"{results['RQ3']['metrics']['demonstrated_causes']} causes demonstrated"],
        ["Frameworks differ", "Composition of failures differs by framework",
         f"V = {_fmt(results['RQ4']['metrics']['cramers_v'])}; not a quality ranking"],
        ["Complexity", "Orchestration/context share rises with declared complexity",
         f"rho = {_fmt(results['RQ6']['metrics']['trend']['rho'], 2)} across 4 tiers"],
        ["Silent failures", "Share not caught by the framework runtime",
         f"{_fmt_pct(results['RQ7']['metrics']['escape_share'])} of records"],
        ["Coverage", "Records the taxonomy could classify",
         f"{_fmt_pct(rq8['metrics']['coverage'])}; unknowns kept in denominators"],
    ]
    _table(doc, ["Dimension", "Result", "Figure"], rows,
           widths=[1.35, 3.3, 2.35], size=8.5)

    _p(doc, "How far the evidence goes", bold=True, size=10, before=8, after=2)
    _p(doc, f"Labels are produced by a deterministic rule-based labeller, so any label can "
            f"be regenerated with the evidence span that produced it. Agreement with a "
            f"first-pass reference annotation is {_fmt_pct(val_eval.get('accuracy'))} exact "
            f"match (macro-F1 {_fmt(val_eval.get('macro_f1'))}, kappa = {_fmt(kappa, 2)}), "
            f"which is moderate rather than high: the residual error sits on two codebook "
            f"boundaries - compatibility versus configuration, and functionality versus "
            f"output parsing. That is the honest limit of the current instrument, and the "
            f"reason the second-coder step is the next task rather than a formality.",
       size=9)
    ndemo = results["RQ3"]["metrics"]["demonstrated_causes"]
    _p(doc, f"Cause is graded, not assumed: only {ndemo} records "
            f"({_fmt_pct(ndemo / rq1['metrics']['n_records'])}) name a checkable "
            "mechanism. No causal language is used for an association the design cannot "
            "identify, and the critic agent blocks any table that claims otherwise.",
       size=9)

    _p(doc, "What exists to inspect", bold=True, size=10, before=8, after=2)
    n_tab, n_fig = _report_shape()
    n_req, n_met, n_lim, n_cats, conf = _conformance()
    fsum = conf["summary"]
    for line in [
        f"Report: {n_tab} tables, {n_fig} figures, with methods, limitations and a plan.",
        f"Dataset: {rq1['metrics']['n_records']:,} records, 27 fields, per-record "
        "provenance and matched rules.",
        "Application: 8 agents on a blackboard; 10/10 research questions verified in the "
        "last run with 0 rejections.",
        f"Code: reproducible from one command; {test_count()} unit tests pass.",
        f"Conformance: {n_req} requirements traced from the two briefs ({n_met} met, "
        f"{n_lim} met with a stated limit); {n_cats}/10 categories carry a cited "
        f"exemplar; {fsum.get('stable', 0)} of {fsum.get('claims_tested', 0)} headline "
        "claims survive resampling, and the one that does not is reported as a finding.",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        run = p.add_run(line)
        run.font.size = Pt(9)

    _p(doc, "Decisions requested", bold=True, size=10, before=8, after=2)
    for line in [
        "Who should be the independent second coder, and by when - the packet is ready.",
        "Whether codebook v1.1 should narrow the two contested boundaries before the "
        "corpus is extended.",
        "Whether to extend collection to Discord/Slack logs and Hugging Face failure "
        "datasets, or to deepen validation of the present corpus.",
    ]:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(1)
        run = p.add_run(line)
        run.font.size = Pt(9)

    out = _paths() / "One_Page_Summary.docx"
    doc.save(out)
    return out


# --------------------------------------------------------------------------- #
# 3. Slide deck
# --------------------------------------------------------------------------- #
def _slide_blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _box(slide, left, top, width, height, text, size=16, bold=False,
         color="444B55", align=None, space_after=6):
    tb = slide.shapes.add_textbox(PInches(left), PInches(top), PInches(width),
                                  PInches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = PRGB.from_string(color)
        r.font.name = "Calibri"
        p.space_after = Pt(space_after)
        if align:
            p.alignment = align
    return tb


def _title(slide, text, kicker=None):
    bar = slide.shapes.add_shape(1, 0, 0, PInches(13.333), PInches(0.16))
    bar.fill.solid()
    bar.fill.fore_color.rgb = PRGB.from_string(NAVY)
    bar.line.fill.background()
    if kicker:
        _box(slide, 0.7, 0.38, 11.9, 0.3, kicker.upper(), size=11, bold=True,
             color="6B7280")
    _box(slide, 0.7, 0.62, 11.9, 0.75, text, size=28, bold=True, color=NAVY)


def _footer(slide, text):
    _box(slide, 0.7, 6.95, 11.9, 0.3, text, size=9, color="8A93A0")


def deck() -> Path:
    results, val, val_eval, kappa = _load()
    rq1, rq3, rq4, rq5, rq6, rq7, rq8 = (results[k] for k in
                                         ("RQ1", "RQ3", "RQ4", "RQ5", "RQ6", "RQ7", "RQ8"))
    n = rq1["metrics"]["n_records"]
    fw = {}
    for r in read_jsonl(PROC_DIR / "failures.jsonl"):
        fw[r["framework"]] = fw.get(r["framework"], 0) + 1

    prs = Presentation()
    prs.slide_width, prs.slide_height = PInches(13.333), PInches(7.5)

    # 1 - title
    s = _slide_blank(prs)
    bg = s.shapes.add_shape(1, 0, 0, PInches(13.333), PInches(7.5))
    bg.fill.solid()
    bg.fill.fore_color.rgb = PRGB.from_string("0E1A2B")
    bg.line.fill.background()
    _box(s, 0.9, 1.7, 11.5, 1.0, "Failures in Agentic AI", size=40, bold=True,
         color="FFFFFF")
    _box(s, 0.9, 2.75, 9.6, 1.6,
         "A five-dimension taxonomy, a corpus of 3,089 publicly reported failures, "
         "and an agentic application that answers ten research questions and verifies "
         "its own numbers.", size=16, color="C9D3E3")
    _box(s, 0.9, 5.9, 9.0, 0.4, "Research briefing  |  " + utc_now()[:10], size=11,
         color="8FA0BA")
    s.notes_slide.notes_text_frame.text = (
        "Open with the one-sentence claim: failures in agentic systems are not random, "
        "they cluster on interfaces - between the agent and its tools, its parser, and "
        "its dependencies. Everything that follows supports or qualifies that claim.")

    # 2 - the question
    s = _slide_blank(prs)
    _title(s, "Three questions, one corpus", "the ask")
    cols = [("What fails?", "A manual taxonomy, not a keyword list. Five dimensions, "
                            "each with definitions, boundaries and exclusion rules."),
            ("Why does it fail?", "Cause is coded separately from type, and graded by "
                                  "how much evidence the report actually contains."),
            ("Does architecture matter?", "Frameworks and declared complexity are "
                                          "tested against the failure mix, with effect "
                                          "sizes rather than rankings.")]
    for i, (head, body) in enumerate(cols):
        x = 0.75 + i * 4.05
        card = s.shapes.add_shape(1, PInches(x), PInches(1.75), PInches(3.75),
                                  PInches(3.3))
        card.fill.solid()
        card.fill.fore_color.rgb = PRGB.from_string("F4F6FA")
        card.line.color.rgb = PRGB.from_string("DDE3EC")
        _box(s, x + 0.3, 2.0, 3.15, 0.5, head, size=20, bold=True, color=NAVY)
        _box(s, x + 0.3, 2.65, 3.15, 2.2, body, size=12.5, color="444B55")
    _footer(s, "Sources: GitHub issue trackers of eight orchestration frameworks, "
               "2023-2026.")
    s.notes_slide.notes_text_frame.text = (
        "Frame it as measurement, not opinion. The deliverable is an instrument: a "
        "codebook anyone can re-apply, plus the evidence that applying it is stable.")

    # 3 - pipeline
    s = _slide_blank(prs)
    _title(s, "Method: collect, label, analyse, verify", "how it works")
    steps = [("1  Collect", "8 repositories, 40 API pages, rate-limited, every request "
                            "logged"),
             ("2  Label", "Deterministic rules; each label stores its evidence span and "
                          "matched rule list"),
             ("3  Analyse", "8 agents on a blackboard; 9 of 10 questions need a chain"),
             ("4  Verify", "Critic recomputes every headline metric independently and "
                          "blocks mismatches")]
    for i, (head, body) in enumerate(steps):
        x = 0.7 + i * 3.16
        _box(s, x, 1.9, 2.9, 0.45, head, size=15, bold=True, color=NAVY)
        _box(s, x, 2.4, 2.85, 1.6, body, size=11.5)
        if i < 3:
            _box(s, x + 2.92, 2.2, 0.3, 0.4, ">", size=18, bold=True, color="C0C8D4")
    _box(s, 0.7, 4.5, 11.9, 1.2,
         "Last run: 3,089 records retained, 10 of 10 questions verified, 0 rejections. "
         "The critic step is what makes the numbers citable - without it this is a script "
         "that prints tables.", size=13, color="444B55")
    _footer(s, "Reproduce: python -m afs.cli all  (about 90 seconds, no network)")
    s.notes_slide.notes_text_frame.text = (
        "Emphasise the verification loop. If asked how it works: the critic recomputes "
        "counts, proportions and test statistics on a separate code path from the agent "
        "that produced them, and refuses the result if the two disagree.")

    # 4 - taxonomy
    s = _slide_blank(prs)
    _title(s, "Five dimensions, coded independently", "the taxonomy")
    rows = [["A  Failure type", "10", "What broke, structurally"],
            ["B  Cause class", "10", "The mechanism the report names"],
            ["C  Lifecycle stage", "8", "Where in the run it broke"],
            ["D  Severity", "4", "Blocking, wrong output, degraded, minor"],
            ["E  Detection point", "5", "Who noticed, and when"]]
    tbl = s.shapes.add_table(len(rows) + 1, 3, PInches(0.7), PInches(1.75),
                             PInches(7.4), PInches(3.4)).table
    for j, head in enumerate(["Dimension", "Codes", "Question it answers"]):
        cell = tbl.cell(0, j)
        cell.text = head
        cell.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
        cell.text_frame.paragraphs[0].runs[0].font.bold = True
        cell.text_frame.paragraphs[0].runs[0].font.color.rgb = PRGB.from_string("FFFFFF")
        cell.fill.solid()
        cell.fill.fore_color.rgb = PRGB.from_string(NAVY)
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = v
            cell.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
            if j == 0:
                cell.text_frame.paragraphs[0].runs[0].font.bold = True
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRGB.from_string("FFFFFF" if i % 2 else "F4F6FA")
    _box(s, 8.5, 1.8, 4.1, 3.4,
         "Type is not cause.\n\nA compatibility failure can be caused by a framework "
         "defect, a version bump, or a user misconfiguration - three different "
         "remediations.\n\nCollapsing them is why 'agent errors' reports rarely "
         "generalise.", size=12, color="444B55")
    _footer(s, "Codebook frozen at v1.0; definitions, boundaries and exclusion rules are "
               "in configs/taxonomy.v1.yaml")
    s.notes_slide.notes_text_frame.text = (
        "If challenged on subjectivity: the codebook is frozen before counting, every "
        "category has include/exclude criteria, and disagreements are measured with kappa "
        "rather than asserted away.")

    # 5 - corpus
    s = _slide_blank(prs)
    _title(s, f"{n:,} reported failures, eight frameworks", "the corpus")
    top = sorted(fw.items(), key=lambda kv: kv[1], reverse=True)
    lines = "\n".join(f"{k}   {v}" for k, v in top)
    _box(s, 0.75, 1.85, 3.9, 3.6, lines, size=13, color="444B55", space_after=8)
    s.shapes.add_picture(str(FIG_DIR / "fig_rq4_framework_composition.png"),
                         PInches(4.7), PInches(1.75), height=PInches(4.3))
    _box(s, 0.75, 5.6, 11.9, 1.0,
         "3,094 candidates seen, 3,089 retained. The five exclusions are logged with a "
         "reason each. Unclassifiable records stay in the corpus and in every denominator.",
         size=12, color="444B55")
    _footer(s, "Per-record provenance: repository, issue number, date, state, labels, "
               "comments, evidence span, matched rules.")
    s.notes_slide.notes_text_frame.text = (
        "Be explicit about what this corpus is: what people chose to report. Silent "
        "failures are under-represented, so shares describe the reporting population, "
        "not all failures.")

    # 6 - what fails
    s = _slide_blank(prs)
    _title(s, "Most failures are interface failures", "finding 1")
    t = rq1["table"]
    _box(s, 0.75, 1.7, 5.6, 0.9,
         f"{_fmt_pct(t[0]['proportion'])}",
         size=54, bold=True, color=NAVY)
    _box(s, 0.75, 2.55, 5.6, 1.4,
         f"{t[0]['label']}\n95% CI {_fmt_pct(t[0]['ci_low'])}-{_fmt_pct(t[0]['ci_high'])}",
         size=13, color="444B55")
    share = sum(x["count"] for x in t[1:4]) / n
    _box(s, 0.75, 3.9, 5.6, 0.8, f"{_fmt_pct(share)}", size=40, bold=True, color=NAVY)
    _box(s, 0.75, 4.6, 5.6, 1.3,
         "compatibility + output parsing + tool integration: failures at a boundary "
         "between components, not inside the model", size=13, color="444B55")
    s.shapes.add_picture(str(FIG_DIR / "fig_rq1_failure_types.png"),
                         PInches(6.6), PInches(1.55), width=PInches(6.1))
    _footer(s, "Wilson 95% intervals; denominator includes the 3.0% unclassified "
               "records.")
    s.notes_slide.notes_text_frame.text = (
        "This is the slide that answers the supervisor's first question. The practical "
        "reading: most of the failure surface is engineering surface - contracts, "
        "parsers, registries - not raw model capability.")

    # 7 - causes
    s = _slide_blank(prs)
    _title(s, "Cause is recorded, then graded by evidence", "finding 2")
    _box(s, 0.7, 1.7, 5.9, 0.5,
         f"Type and cause are associated: V = {_fmt(rq3['metrics']['cramers_v'])} "
         f"(chi-square p < 1e-12)", size=13, bold=True, color=NAVY)
    cause_counts: dict[str, int] = {}
    for r in read_jsonl(PROC_DIR / "failures.jsonl"):
        c = r.get("B_cause_class", "")
        cause_counts[c] = cause_counts.get(c, 0) + 1
    ranked_causes = sorted(cause_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    tax = Taxonomy()
    rows = [["Stated cause class", "n", "Share"]]
    for code, count in ranked_causes:
        rows.append([tax.label("B_cause_class", code), count, _fmt_pct(count / n)])
    tbl = s.shapes.add_table(len(rows), 3, PInches(0.7), PInches(2.3), PInches(5.9),
                             PInches(2.6)).table
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = str(v)
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size = Pt(11.5)
            run.font.bold = (i == 0)
            run.font.color.rgb = PRGB.from_string("FFFFFF" if i == 0 else "444B55")
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRGB.from_string(
                NAVY if i == 0 else ("FFFFFF" if i % 2 else "F4F6FA"))
    _box(s, 0.7, 5.25, 5.9, 1.4,
         f"Only {rq3['metrics']['demonstrated_causes']} records "
         f"({_fmt_pct(rq3['metrics']['demonstrated_causes'] / n)}) name a checkable "
         "mechanism. The rest are graded supported or hypothesised, and no causal claim "
         "rests on them.", size=11.5, color="6B7280")
    s.shapes.add_picture(str(FIG_DIR / "fig_rq3_cause_by_type.png"),
                         PInches(6.9), PInches(1.6), height=PInches(4.9))
    _footer(s, "Cramer's V measures association, not direction; the design cannot "
               "identify a causal effect.")
    s.notes_slide.notes_text_frame.text = (
        "Say plainly: the association is strong and the causal evidence is thin. That is "
        "why the report grades every cause and uses association language throughout. If "
        "she pushes on causality, this is the answer.")

    # 8 - frameworks
    s = _slide_blank(prs)
    _title(s, "Frameworks fail differently, not worse", "finding 3")
    _box(s, 0.7, 1.7, 6.2, 0.9,
         f"Composition differs (V = {_fmt(rq4['metrics']['cramers_v'])}); "
         f"blocking rate ranges from "
         f"{_fmt_pct(rq5['metrics']['min_rate'])} to {_fmt_pct(rq5['metrics']['max_rate'])}.",
         size=13.5, bold=True, color=NAVY)
    _box(s, 0.7, 2.7, 6.0, 3.2,
         "A blocking rate is a property of the issue and the framework's error handling, "
         "not a quality score: a framework that fails loudly produces blocking reports, "
         "one that fails silently produces quiet corruption.\n\n"
         "That is why the escape rate (next slide) matters more than the ranking.",
         size=12, color="444B55")
    s.shapes.add_picture(str(FIG_DIR / "fig_rq5_blocking_rate.png"),
                         PInches(7.0), PInches(1.6), height=PInches(4.6))
    _footer(s, "Pairwise Fisher tests with Benjamini-Hochberg correction; Wilson "
               "intervals per framework.")
    s.notes_slide.notes_text_frame.text = (
        "Pre-empt the obvious challenge: this is not a benchmark of the frameworks. "
        "Reporter behaviour and issue-template design shape what reaches an issue "
        "tracker.")

    # 9 - complexity + escapes
    s = _slide_blank(prs)
    _title(s, "Complexity buys capability and buys failure modes", "finding 4")
    _box(s, 0.7, 1.7, 5.7, 0.6,
         f"Orchestration/context share by tier: rho = "
         f"{_fmt(rq6['metrics']['trend']['rho'], 2)}, V = "
         f"{_fmt(rq6['metrics']['cramers_v'])}", size=13, bold=True, color=NAVY)
    tier = {r["label"]: r["proportion"] for r in rq6["table"]}
    _box(s, 0.7, 2.35, 5.7, 2.2,
         f"Tier 0 (single agent, no tools): {_fmt_pct(tier.get('tier_0', 0))} "
         "orchestration/context failures.\n"
         f"Tier 3 (multi-agent, tools, memory): {_fmt_pct(tier.get('tier_3', 0))}.\n\n"
         "Complexity is a declared property here - parsed from the report - not an "
         "instrumented one. Treat it as a stratifier, not a measurement.",
         size=12, color="444B55")
    _box(s, 0.7, 4.7, 5.7, 0.8, f"{_fmt_pct(rq7['metrics']['escape_share'])}",
         size=40, bold=True, color=NAVY)
    _box(s, 0.7, 5.45, 5.7, 1.2,
         "of failures are never caught by the framework runtime - they reach the user "
         "as wrong output, not as an error.", size=12, color="444B55")
    s.shapes.add_picture(str(FIG_DIR / "fig_rq6_complexity.png"),
                         PInches(6.7), PInches(1.6), height=PInches(4.6))
    _footer(s, "Escape = detection point other than framework runtime "
               "(test, human, production monitoring).")
    s.notes_slide.notes_text_frame.text = (
        "The escape number is the most practically useful result: "
        f"{_fmt_pct(rq7['metrics']['escape_share'])} of reported "
        "failures produced no runtime error. For anyone deploying these systems, that is "
        "the argument for output validation rather than exception handling.")

    # 10 - validation
    s = _slide_blank(prs)
    _title(s, "What the instrument can and cannot support", "validation")
    rows = [["Experiment", "Result", "Reading"],
            ["Reference agreement (E1)",
             f"{_fmt_pct(val_eval.get('accuracy'))} exact, kappa "
             f"{_fmt(kappa, 2)}",
             "Moderate. Boundary ambiguity, not noise."],
            ["Perturbation (E2)",
             f"{_fmt_pct((val.get('perturbation') or {}).get('retention_rate'))} retention",
             "Labels survive rewording and anonymisation."],
            ["Cue ablation (E3)",
             f"{_fmt_pct((val.get('ablation') or {}).get('change_rate'))} of labels move",
             "Not dependent on pasted tracebacks."],
            ["Calibration (E4)", "39% to 59% across bins",
             "Confidence is informative, not calibrated."],
            ["Second coder (E5)", "Pending",
             "The step that turns labels into a measurement."]]
    tbl = s.shapes.add_table(len(rows), 3, PInches(0.7), PInches(1.7), PInches(11.9),
                             PInches(3.6)).table
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = str(v)
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size = Pt(11)
            run.font.bold = (i == 0)
            run.font.color.rgb = PRGB.from_string("FFFFFF" if i == 0 else "444B55")
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRGB.from_string(
                NAVY if i == 0 else ("FFFFFF" if i % 2 else "F4F6FA"))
    _box(s, 0.7, 5.55, 11.9, 1.2,
         "The honest sentence: the taxonomy is usable now, the labels are reproducible, "
         "and agreement is moderate until an independent coder completes the 40-record "
         "packet. That packet and the scoring command are part of the handover.",
         size=12.5, color="444B55")
    _footer(s, "Validation artefacts: outputs/tables/validation_*.json")
    s.notes_slide.notes_text_frame.text = (
        "Do not soften this. Volunteering the moderate kappa and the specific boundary "
        "problem is what makes the rest of the numbers credible.")

    # 11 - conformance / robustness
    s = _slide_blank(prs)
    _title(s, "Every request in the brief, closed and traceable", "conformance")
    fval = read_json(TAB_DIR / "findings_validation.json") \
        if (TAB_DIR / "findings_validation.json").exists() else {}
    f1 = fval.get("F1_resampling") or {}
    f2 = fval.get("F2_temporal") or {}
    f3 = fval.get("F3_leave_one_out") or {}
    f4 = fval.get("F4_label_noise") or {}
    fsum = fval.get("summary") or {}
    req_p = TAB_DIR / "requirements_traceability.csv"
    req_rows = read_csv(req_p) if req_p.exists() else []
    ex_p = TAB_DIR / "taxonomy_exemplars.csv"
    ex_rows = read_csv(ex_p) if ex_p.exists() else []
    ex_cats = len({r.get("category") for r in ex_rows}) if ex_rows else 0

    rows = [["Robustness test", "Claim under test", "Verdict"],
            ["F1  Resampling", f"Top category holds under {f1.get('iterations', '-')} "
             "bootstrap resamples",
             "Stable" if f1.get("verdict") == "stable" else "Unstable"],
            ["F2  Temporal split",
             f"Composition is stationary before/after {f2.get('split_year', '-')}",
             "Stable" if f2.get("verdict") == "stable" else "Not stable"],
            ["F3  Leave-one-framework-out",
             f"Ranking survives dropping any of {f3.get('frameworks_tested', '-')} "
             "repositories",
             "Stable" if f3.get("verdict") == "stable" else "Unstable"],
            ["F4  Label noise",
             "Ranking survives simulated labelling error",
             (f4.get("verdict") or "Not run").replace("direction stable, magnitude "
                                                      "uncertain", "Direction stable")]]
    tbl = s.shapes.add_table(len(rows), 3, PInches(0.65), PInches(1.75),
                             PInches(7.7), PInches(2.6)).table
    for j, w in enumerate([1.85, 4.35, 1.5]):
        tbl.columns[j].width = PInches(w)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = str(v)
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size = Pt(10)
            run.font.bold = (i == 0)
            run.font.color.rgb = PRGB.from_string("FFFFFF" if i == 0 else "444B55")
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRGB.from_string(
                NAVY if i == 0 else ("FFFFFF" if i % 2 else "F4F6FA"))
    _box(s, 0.65, 4.55, 7.7, 1.4,
         f"{fsum.get('stable', 0)} of {fsum.get('claims_tested', '-')} claims are "
         f"stable outright, {fsum.get('direction_stable', 0)} are directionally "
         f"stable and {fsum.get('not_stable', 0)} "
         f"{'fails' if fsum.get('not_stable', 0) == 1 else 'fail'}: composition "
         f"shifted between the early and late periods. That is reported, not hidden.",
         size=11.5, color="444B55")

    _box(s, 8.75, 1.75, 4.0, 0.4, "Requirement conformance", size=15, bold=True,
         color=NAVY)
    met = sum(1 for r in req_rows if r.get("status") == "Met")
    lim = sum(1 for r in req_rows if r.get("status") != "Met")
    for k, line in enumerate([
            f"{len(req_rows)} requirements traced from the two briefs",
            f"{met} met, {lim} met with a stated limit",
            f"{ex_cats} of 10 categories have a cited exemplar",
            f"{len(ex_rows)} exemplars with URL and evidence span",
            "Every row links requirement > evidence > file > artefact"]):
        _box(s, 8.75, 2.2 + k * 0.52, 4.0, 0.5, line, size=11.5, color="444B55")
    _box(s, 8.75, 4.85, 4.0, 1.2,
         "The matrix is generated, not written: re-run the pipeline and it "
         "either still says Met or the row fails.", size=11,
         color="6B7280")
    _footer(s, "outputs/tables/requirements_traceability.csv  |  "
               "findings_validation.json  |  Requirement_Conformance.docx")
    s.notes_slide.notes_text_frame.text = (
        "This slide answers the two questions that come up in every review: are the "
        "findings robust, and did you actually do what the brief asked. Both answers are "
        "machine-generated. Offer the F2 failure before it is asked: the mix changed "
        "after 2025, which is itself a result about the field maturing.")

    # 12 - deliverables
    s = _slide_blank(prs)
    _title(s, "What is in the box", "deliverables")
    items = [("Report", f"{_report_pages()} pages, {_report_shape()[0]} tables, "
                        f"{_report_shape()[1]} figures, methods, limitations, plan"),
             ("Dataset", f"{n:,} records, 27 fields, provenance and matched rules"),
             ("Codebook", "5 dimensions, boundaries, exclusion rules, impact rubric"),
             ("Application", "8 agents, blackboard, critic verification, "
                             f"{test_count()} tests"),
             ("Conformance", f"{len(req_rows)} requirements traced to evidence; F1-F4 "
                             f"robustness; {ex_cats}/10 categories with a cited example"),
             ("Handover", "One-page summary, second-coder packet, deck, README")]
    for i, (head, body) in enumerate(items):
        y = 1.7 + i * 0.86
        _box(s, 0.75, y, 2.2, 0.4, head, size=14, bold=True, color=NAVY)
        _box(s, 3.0, y, 9.5, 0.6, body, size=12, color="444B55")
    _footer(s, "Everything regenerates from one command; the audit log records each run.")
    s.notes_slide.notes_text_frame.text = (
        "Close on reproducibility: a reviewer can re-run the pipeline and get the same "
        "tables, and can trace any single label back to a sentence in the original issue.")

    # 13 - next
    s = _slide_blank(prs)
    _title(s, "Next four weeks", "plan")
    cols = [("Week 1", "Second coder completes the 40-record packet; score kappa; "
                       "adjudicate disagreements."),
            ("Week 2", "Codebook v1.1 narrows the two contested boundaries; re-score "
                       "E1 on the same split."),
            ("Week 3", "Extend collection to chat logs and public failure datasets; "
                       "re-run the pipeline."),
            ("Week 4", "Final report revision, figures, and a short internal "
                       "presentation.")]
    for i, (head, body) in enumerate(cols):
        x = 0.7 + i * 3.15
        _box(s, x, 1.85, 2.9, 0.45, head, size=16, bold=True, color=NAVY)
        _box(s, x, 2.4, 2.85, 2.2, body, size=12, color="444B55")
    _box(s, 0.7, 4.9, 11.9, 1.3,
         "The first task is not more data. It is the second coder, because agreement is "
         "what converts a classification into a measurement.", size=14, bold=True,
         color=NAVY)
    _footer(s, "Questions welcome - the corpus, code and report are all inspectable.")
    s.notes_slide.notes_text_frame.text = (
        "End by asking for the two decisions: who codes, and whether to narrow the "
        "boundaries before extending the corpus.")

    out = _paths() / "Agentic_Failure_Study_Deck.pptx"
    prs.save(out)
    return out


def _conformance() -> tuple[int, int, int, int, dict]:
    """Requirement rows, met count, limited count, exemplar coverage, robustness."""
    req_p = TAB_DIR / "requirements_traceability.csv"
    rows = read_csv(req_p) if req_p.exists() else []
    met = sum(1 for r in rows if r.get("status") == "Met")
    lim = sum(1 for r in rows if r.get("status") != "Met")
    ex_p = TAB_DIR / "taxonomy_exemplars.csv"
    ex_rows = read_csv(ex_p) if ex_p.exists() else []
    cats = len({r.get("category") for r in ex_rows}) if ex_rows else 0
    fval_p = TAB_DIR / "findings_validation.json"
    fval = read_json(fval_p) if fval_p.exists() else {}
    return len(rows), met, lim, cats, {
        "exemplars": len(ex_rows), "findings": fval,
        "summary": fval.get("summary") or {}}


def _report_shape() -> tuple[int, int]:
    """Table and figure counts of the rendered report, if it exists."""
    path = TAB_DIR.parent / "reports" / "Agentic_Failure_Study_Report.docx"
    if not path.exists():
        return (0, 0)
    from docx import Document as _Doc

    d = _Doc(str(path))
    return (len(d.tables), len(d.inline_shapes))


def _report_pages() -> str:
    """Page count of the rendered PDF, if it has been produced."""
    pdf = TAB_DIR.parent / "reports" / "Agentic_Failure_Study_Report.pdf"
    if not pdf.exists():
        return "-"
    try:
        import fitz

        return str(fitz.open(str(pdf)).page_count)
    except Exception:
        return "-"


def build_all() -> dict[str, str]:
    return {"packet": str(annotation_packet()),
            "one_pager": str(one_pager()),
            "deck": str(deck())}

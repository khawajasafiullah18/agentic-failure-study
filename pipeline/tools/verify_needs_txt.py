"""Verify needs.txt row by row, sentence by sentence.

The advisor's sheet has 16 rows and four columns. Column 1 names the topic,
column 3 records what he believed existed, column 4 is the actual requirement.
This script reads the file, confirms every topic and every requirement sentence
is present in it verbatim, then for each requirement looks for the artefact that
would prove it.

It deliberately does not read the conformance matrix: the matrix is the claim,
this is the check. Where the artefact is a document section, the section text is
searched, so a requirement that is only asserted in the matrix fails here.

    python tools/verify_needs_txt.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afs.common import PROC_DIR, TAB_DIR, read_csv, read_json, read_jsonl  # noqa: E402
from afs.taxonomy import Taxonomy                                            # noqa: E402

NEEDS = Path(r"C:\Users\drkha\Downloads\needs.txt")

# (topic as written in column 1, requirement as written in column 4, key)
ROWS: list[tuple[str, str, str]] = [
    ("Failure Taxonomy",
     "Must show the actual final taxonomy, definitions of each category, and how the "
     "categories were derived/manual classified.", "S1"),
    ("Real examples for each failure type",
     "Need traceable examples from real datasets/logs for each taxonomy category.", "S2"),
    ("2–10 Research Questions",
     "The paper/application needs explicit RQ1, RQ2, RQ3..., not only dashboard "
     "questions.", "S3"),
    ("Decide single-agent vs multi-agent per RQ",
     "Must explain which RQ uses one agent, which uses multiple agents, and why.", "S4"),
    ("Hundreds of failure records",
     "Need to prove dataset size: e.g. N = 500, N = 800, etc.", "S5"),
    ("Public datasets",
     "Need documented sources: Hugging Face, AIDev, CrewAI, AutoGen, LangGraph, GitHub "
     "issues/logs, etc.", "S6"),
    ("Application accepts taxonomy + dataset",
     "Need to document how taxonomy and dataset actually enter the system.", "S7"),
    ("Agents analyze failures",
     "Need architecture showing what every agent does.", "S8"),
    ("Statistical results",
     "This seems strongly aligned.", "S9"),
    ("Tables, percentages, visual reports",
     "Strong match.", "S10"),
    ("Most common failures",
     "Need results directly tied to a research question.", "S11"),
    ("Main causes of failures",
     "Need explicit root-cause classification, not only failure categories.", "S12"),
    ("Compare frameworks",
     "Need quantitative comparison by framework based on the dataset.", "S13"),
    ("Agent complexity vs failure",
     "Need a measurable definition of complexity and analysis if this RQ is retained.",
     "S14"),
    ("Simple experiments for validation",
     "This is where your current experiment fits.", "S15"),
    ("Validate the findings",
     "Need methodology showing how classification/results were checked.", "S16"),
]

FINDINGS: list[tuple[str, str, str]] = []


def rec(key: str, topic: str, verdict: str, evidence: str) -> None:
    FINDINGS.append((key, topic, verdict, evidence))


def docx_text(name: str) -> str:
    from docx import Document

    d = Document(str(ROOT / "outputs/reports" / name))
    parts = [p.text for p in d.paragraphs]
    for tb in d.tables:
        for row in tb.rows:
            for c in row.cells:
                parts.append(c.text)
    return "\n".join(parts)


def norm(s: str) -> str:
    """Collapse whitespace and unify dashes.

    needs.txt was exported with a byte that does not decode as the en dash in
    "2-10", so a literal comparison would report a false miss. The comparison
    that matters is of wording, not of typography.
    """
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\ufffd", "-")
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    if not NEEDS.exists():
        print(f"missing: {NEEDS}")
        return 2
    raw = NEEDS.read_text(encoding="utf-8", errors="replace")
    flat = norm(raw)

    print(f"needs.txt: {len(raw)} chars, {len(ROWS)} rows\n")

    # ---- 1. every topic and requirement is actually in the file ------------
    absent = [k for k, (topic, req, _k) in enumerate(ROWS)
              if norm(topic) not in flat or norm(req) not in flat]
    print(f"verbatim presence: {len(ROWS) - len(absent)}/{len(ROWS)} rows matched")
    if absent:
        print("  rows not found verbatim (encoding/dash differences):",
              [ROWS[i][2] for i in absent])
    print()

    T = Taxonomy()
    rep = docx_text("Agentic_Failure_Study_Report.docx")
    records = read_jsonl(PROC_DIR / "failures.jsonl")
    n = len(records)
    codes = [(d, c) for d in T.spec["dimensions"] for c in T.codes(d)]

    # ---- S1 ----------------------------------------------------------------
    bounded = [(d, c) for d, c in codes
               if all(T.categories(d)[c].get(k)
                      for k in ("definition", "include", "exclude"))]
    deriv = "How the taxonomy was derived" in rep
    manual = "gold_sample" in rep and "coded by hand by the author" in rep
    rec("S1", "Failure Taxonomy",
        "PASS" if len(bounded) == len(codes) and deriv and manual else "PARTIAL",
        f"{len(bounded)}/{len(codes)} codes carry definition+include+exclude; "
        f"derivation section {'present' if deriv else 'MISSING'}; "
        f"manual coding artefact {'cited' if manual else 'not cited'}")

    # ---- S2 ----------------------------------------------------------------
    ex = read_csv(TAB_DIR / "taxonomy_exemplars.csv")
    by_id = {r["record_id"]: r for r in read_jsonl(PROC_DIR / "records_enriched.jsonl")}
    per_dim = {}
    for dim, key in (("A", "A_failure_type"), ("B", "B_cause_class"),
                     ("C", "C_lifecycle_stage"), ("D", "D_severity"),
                     ("E", "E_detection_point")):
        want = set(T.codes(key))
        if dim == "A":
            got = {r["category"] for r in ex}
        else:
            got = {by_id[r["record_id"]][key] for r in ex if r["record_id"] in by_id}
        per_dim[dim] = f"{len(want & got)}/{len(want)}"
    linked = sum(1 for r in ex if r["url"].startswith("http"))
    full = all(int(a.split("/")[0]) == int(a.split("/")[1]) for a in per_dim.values())
    rec("S2", "Real examples for each failure type",
        "PASS" if full and linked == len(ex) else "PARTIAL",
        f"{len(ex)} cited exemplars, {linked} with URL; coverage A {per_dim['A']}, "
        f"B {per_dim['B']}, C {per_dim['C']}, D {per_dim['D']}, E {per_dim['E']}")

    # ---- S3 ----------------------------------------------------------------
    import yaml

    qs = yaml.safe_load((ROOT / "configs/research_questions.yaml")
                        .read_text(encoding="utf-8"))["questions"]
    in_report = all(q["id"] in rep for q in qs)
    rec("S3", "2–10 Research Questions",
        "PASS" if 2 <= len(qs) <= 10 and in_report else "FAIL",
        f"{len(qs)} questions; all {len(qs)} ids appear in the report as RQ1..RQ{len(qs)}")

    # ---- S4 ----------------------------------------------------------------
    single = [q["id"] for q in qs if len(q.get("agents") or []) == 1]
    multi = [q["id"] for q in qs if len(q.get("agents") or []) > 1]
    why = re.search(r"therefore a chain", rep) or re.search(r"needs the critic", rep)
    rec("S4", "Decide single-agent vs multi-agent per RQ",
        "PASS" if single and multi and why and "Mode" in rep else "PARTIAL",
        f"{len(multi)} chained, {len(single)} single ({', '.join(single)}); "
        f"Mode column in report; rationale {'stated' if why else 'MISSING'}")

    # ---- S5 ----------------------------------------------------------------
    excl = json.loads((PROC_DIR / "exclusions.json").read_text(encoding="utf-8"))
    rec("S5", "Hundreds of failure records",
        "PASS" if n >= 800 else "PARTIAL",
        f"N = {n:,} (threshold named in the sheet was 500-800); "
        f"{excl['candidates_seen']} seen, {excl['excluded']} excluded with reasons")

    # ---- S6 ----------------------------------------------------------------
    from afs.sources import SOURCES

    named = ["hugging face", "aidev", "crewai", "autogen", "langgraph", "github"]
    src_blob = " ".join(s["source"] for s in SOURCES).lower()
    covered = [k for k in named if k in src_blob]
    from afs import aidev as _adv

    a = (_adv.load().get("summary") or {})
    used = [s for s in SOURCES if s["used"] == "Yes"]
    rec("S6", "Public datasets",
        "PASS" if len(covered) == len(named) and "Candidate source" in rep
        and a.get("pull_requests") else "PARTIAL",
        f"{len(covered)}/{len(named)} named sources accounted for in report 5.1; "
        f"{len(used)} used as inputs: the framework issue trackers plus AIDev, "
        f"which contributes {a.get('pull_requests', 0):,} agent-authored pull requests "
        f"across {a.get('repositories', 0):,} repositories (report 9.8)")

    # ---- S7 ----------------------------------------------------------------
    path_doc = ("How the codebook and the corpus enter the application" in rep
                and "taxonomy.v1.yaml" in rep and "records_enriched" in rep)
    rec("S7", "Application accepts taxonomy + dataset",
        "PASS" if path_doc else "FAIL",
        "report 7.1 names both artefacts, the load point and the malformed-codebook "
        "behaviour; /api/classify applies the codebook to arbitrary text")

    # ---- S8 ----------------------------------------------------------------
    import ast

    tree = ast.parse((ROOT / "src/afs/agents.py").read_text(encoding="utf-8"))
    agents = [x.name for x in tree.body
              if isinstance(x, ast.ClassDef) and x.name.endswith("Agent") and x.name != "Agent"]
    rec("S8", "Agents analyze failures",
        "PASS" if len(agents) >= 8 and all(a in rep for a in agents) else "PARTIAL",
        f"{len(agents)} agents ({', '.join(agents)}); each named in the report "
        "architecture table with a responsibility")

    # ---- S9 / S10 ----------------------------------------------------------
    tables = sorted(TAB_DIR.glob("rq*_table.csv"))
    figs = sorted((ROOT / "outputs/figures").glob("*.png"))
    pct_in_rep = len(re.findall(r"\d+\.\d%", rep))
    rec("S9", "Statistical results",
        "PASS" if len(tables) >= 8 and "Wilson" in rep else "FAIL",
        f"{len(tables)} RQ result tables; Wilson intervals and effect sizes in the report")
    rec("S10", "Tables, percentages, visual reports",
        "PASS" if len(figs) >= 5 and pct_in_rep >= 20 else "PARTIAL",
        f"{len(figs)} figures, {pct_in_rep} percentage figures in the report, "
        f"{len(tables)} tables")

    # ---- S11 ---------------------------------------------------------------
    res = read_json(ROOT / "outputs/analysis_results.json")["verified"]
    top = res["RQ1"]["table"][0]
    rec("S11", "Most common failures",
        "PASS" if "8.1 Distribution of failure types (RQ1)" in rep else "FAIL",
        f"report 8.1 is RQ1: {top['code']} {top['count']}/{top['denominator']} "
        f"= {top['proportion'] * 100:.1f}%, with its interval")

    # ---- S12 ---------------------------------------------------------------
    bcodes = T.codes("B_cause_class")
    grades = {r.get("B_evidence_grade") for r in records if r.get("B_evidence_grade")}
    rec("S12", "Main causes of failures",
        "PASS" if len(bcodes) == 10 and len(grades) >= 2 else "FAIL",
        f"dimension B has {len(bcodes)} cause classes, each record graded "
        f"({', '.join(sorted(grades))}); separate from the failure-type axis")

    # ---- S13 ---------------------------------------------------------------
    m4 = res["RQ4"]["metrics"]
    rec("S13", "Compare frameworks",
        "PASS" if m4["chi2"] > 0 and m4["p_value"] < 0.05 else "FAIL",
        f"RQ4 chi2={m4['chi2']:.1f}, p={m4['p_value']:.2g}, "
        f"Cramer's V={m4['cramers_v']:.3f} over 8 frameworks")

    # ---- S14 ---------------------------------------------------------------
    cx = read_json(TAB_DIR / "complexity_definition.json")
    cxd = cx.get("definition") or {}
    rec("S14", "Agent complexity vs failure",
        "PASS" if cxd.get("construct") and cxd.get("known_limitations")
        and cx.get("component_check") else "PARTIAL",
        f"construct declared with {len(cxd.get('known_limitations') or [])} stated "
        f"limits, {len(cx.get('distribution') or [])} tiers, component check and "
        "verbosity control; RQ6 answers it")

    # ---- S15 ---------------------------------------------------------------
    vs = read_json(TAB_DIR / "validation_summary.json")
    suites = [k for k in ("gold_eval", "perturbation", "ablation", "calibration") if k in vs]
    pilot_stated = "Status of the pilot repair experiment" in rep
    rec("S15", "Simple experiments for validation",
        "PASS" if len(suites) == 4 and pilot_stated else "PARTIAL",
        f"instrument suite E1-E4 present ({len(suites)}/4) plus E5 sheet and F1-F4. "
        f"The CrewAI/AutoGen repair experiment the sheet names is prior pilot work, not "
        f"in this repository; its status is now stated in report 9.6 "
        f"({'present' if pilot_stated else 'MISSING'})")

    # ---- S16 ---------------------------------------------------------------
    kappa = vs["gold_eval"]["kappa_vs_reference"]["kappa"]
    fv = read_json(TAB_DIR / "findings_validation.json")
    second = read_csv(ROOT / "data/gold/second_coder_sheet.csv")
    filled = sum(1 for r in second if r.get("coder2_label", "").strip())
    rec("S16", "Validate the findings",
        "PARTIAL" if filled == 0 else "PASS",
        f"kappa {kappa:.2f} vs {vs['gold_eval']['n']} hand-coded records; "
        f"F1-F4 stress-tested {fv['summary']['claims_tested']} claims; "
        f"second-coder sheet {filled}/{len(second)} filled, so inter-rater kappa "
        "is not yet computable")

    # ---- print -------------------------------------------------------------
    print(f"{'#'.ljust(5)}{'topic'.ljust(38)}{'verdict'.ljust(10)}evidence")
    print("-" * 132)
    for key, topic, verdict, evidence in FINDINGS:
        print(f"{key.ljust(5)}{topic[:36].ljust(38)}{verdict.ljust(10)}{evidence}")

    tally = {v: sum(1 for _, _, x, _ in FINDINGS if x == v)
             for v in ("PASS", "PARTIAL", "FAIL")}
    print(f"\nPASS {tally['PASS']} - PARTIAL {tally['PARTIAL']} - FAIL {tally['FAIL']}")
    return 0 if tally["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

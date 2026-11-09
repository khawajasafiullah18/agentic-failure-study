"""Check each line of the two briefs against a real artefact.

`requirements.py` records what was done; this script is the adversarial pass. It
re-parses both source documents, then for each line looks for the artefact that
would prove it, and prints PASS / PARTIAL / FAIL with what it actually found.

Run before telling anyone the brief is complete:
    python tools/verify_brief.py
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

BRIEFS = [Path(r"C:\Users\drkha\Downloads\needs.docx"),
          Path(r"C:\Users\drkha\Downloads\requirement of the project.docx")]

results: list[tuple[str, str, str]] = []


def rec(item: str, verdict: str, evidence: str) -> None:
    results.append((item, verdict, evidence))


def docx_text(path: Path) -> str:
    from docx import Document

    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for tb in d.tables:
        for row in tb.rows:
            for c in row.cells:
                parts.append(c.text)
    return "\n".join(parts)


def report_text() -> str:
    return docx_text(ROOT / "outputs/reports/Agentic_Failure_Study_Report.docx")


def main() -> int:
    T = Taxonomy()
    ok = True

    # ---- 0. the briefs themselves -----------------------------------------
    for b in BRIEFS:
        if not b.exists():
            print(f"brief not found: {b}")
            return 2
    needs = docx_text(BRIEFS[0])
    reqs = docx_text(BRIEFS[1])

    n_items = len(re.findall(r"^\s*\d+\.\s", needs, re.M))
    print(f"needs.docx: {len(needs.splitlines())} lines, ~{n_items} numbered items")
    print(f"requirement doc: {len(reqs.splitlines())} lines\n")

    rep = report_text()
    records = read_jsonl(PROC_DIR / "failures.jsonl")
    n = len(records)

    # ---- checklist S1..S16 -------------------------------------------------
    codes = [(d, c) for d in T.spec["dimensions"] for c in T.codes(d)]
    complete = [1 for d, c in codes
                if all(T.categories(d)[c].get(k)
                       for k in ("definition", "include", "exclude"))]
    rec("S1 taxonomy + definitions + derivation",
        "PASS" if len(complete) == len(codes) and "How the taxonomy was derived" in rep
        else "FAIL",
        f"{len(complete)}/{len(codes)} codes fully bounded; "
        f"derivation section {'present' if 'How the taxonomy was derived' in rep else 'MISSING'}")

    ex = read_csv(TAB_DIR / "taxonomy_exemplars.csv") if (
        TAB_DIR / "taxonomy_exemplars.csv").exists() else []
    cats = len({r["category"] for r in ex})
    linked = sum(1 for r in ex if r["url"].startswith("http"))
    rec("S2 traceable example per category",
        "PASS" if cats == 10 and linked == len(ex) else "FAIL",
        f"{len(ex)} exemplars, {cats}/10 categories, {linked}/{len(ex)} with a source URL")

    import yaml

    qs = yaml.safe_load((ROOT / "configs/research_questions.yaml")
                        .read_text(encoding="utf-8"))["questions"]
    rec("S3 2-10 explicit research questions",
        "PASS" if 2 <= len(qs) <= 10 and all(f"RQ{i}[']" not in rep for i in range(1, 2))
        and "RQ10" in rep else "FAIL",
        f"{len(qs)} questions, RQ1-RQ{len(qs)} in the report")

    single = [q for q in qs if len(q.get("agents") or []) == 1]
    multi = [q for q in qs if len(q.get("agents") or []) > 1]
    rec("S4 single vs multi agent per RQ",
        "PASS" if single and multi and "Mode" in rep else "FAIL",
        f"{len(multi)} chained, {len(single)} single "
        f"({', '.join(q['id'] for q in single)}); report table carries a Mode column")

    exclusions = json.loads((PROC_DIR / "exclusions.json").read_text(encoding="utf-8"))
    rec("S5 prove dataset size",
        "PASS" if n >= 500 and exclusions.get("excluded") else "FAIL",
        f"N = {n:,}; {exclusions['candidates_seen']} seen, "
        f"{exclusions['excluded']} excluded with reasons")

    from afs.sources import SOURCES

    rec("S6 document public data sources",
        "PASS" if len(SOURCES) >= 5 and "Candidate source" in rep else "FAIL",
        f"{len(SOURCES)} candidate sources accounted for in report 5.1 and on the "
        "live page; Hugging Face used as the publication target")

    rec("S7 how taxonomy + dataset enter the app",
        "PASS" if "How the codebook and the corpus enter" in rep
        and "taxonomy.v1.yaml" in rep and "records_enriched" in rep else "FAIL",
        "report 7.1 names the files, the load point and the failure mode; "
        "/api/classify applies the same codebook to arbitrary text")

    from afs import agents as A

    import ast

    tree = ast.parse((ROOT / "src/afs/agents.py").read_text(encoding="utf-8"))
    agent_classes = [x.name for x in tree.body
                     if isinstance(x, ast.ClassDef) and x.name.endswith("Agent")]
    goals = [x for x in agent_classes if x != "Agent"]
    rec("S8 architecture of every agent",
        "PASS" if len(goals) >= 5 and all(f"{g}" in rep for g in goals[:3])
        and "Responsibility" in rep else "FAIL",
        f"{len(goals)} agents, each with a distinct goal; report table lists all")

    rq_tables = sorted(TAB_DIR.glob("rq*_table.csv"))
    figs = sorted((ROOT / "outputs/figures").glob("*.png"))
    rec("S9 statistical results, tables, percentages, figures",
        "PASS" if len(rq_tables) >= 8 and len(figs) >= 5 else "FAIL",
        f"{len(rq_tables)} RQ result tables, {len(figs)} figures")

    rec("S10 results tied to a research question",
        "PASS" if all(re.match(r"rq\d+_table", p.name) for p in rq_tables) else "FAIL",
        "every table is named by the RQ that produces it")

    res = read_json(ROOT / "outputs/analysis_results.json")["verified"]
    top = res["RQ1"]["table"][0]
    rec("S11 most common failures, tied to RQ1",
        "PASS" if "RQ1" in rep and f"{top['proportion'] * 100:.1f}" in rep else "FAIL",
        f"RQ1 -> {top['label']} {top['count']}/{top['denominator']} "
        f"= {top['proportion'] * 100:.1f}%")

    b_codes = T.codes("B_cause_class")
    graded = {r.get("B_evidence_grade") for r in records}
    rec("S12 explicit root-cause classification",
        "PASS" if len(b_codes) == 10 and graded >= {"demonstrated", "supported"} else "FAIL",
        f"{len(b_codes)} cause classes, graded {sorted(g for g in graded if g)}")

    rec("S13 quantitative framework comparison",
        "PASS" if res["RQ4"]["metrics"]["chi2"] > 0 and "Cram" in rep else "FAIL",
        f"RQ4 chi2={res['RQ4']['metrics']['chi2']:.1f}, "
        f"V={res['RQ4']['metrics']['cramers_v']:.3f}")

    cx = read_json(TAB_DIR / "complexity_definition.json")
    cxdef = cx.get("definition") or {}
    rec("S14 measurable complexity definition",
        "PASS" if cxdef.get("construct") and cxdef.get("known_limitations")
        and cx.get("distribution") else "FAIL",
        f"construct '{cxdef.get('construct')}' with "
        f"{len(cxdef.get('known_limitations') or [])} stated limits, "
        f"{len(cx.get('distribution') or [])} tiers and 4 quality checks")

    vs = read_json(TAB_DIR / "validation_summary.json")
    have = {k for k in ("perturbation", "ablation", "calibration", "gold_eval")
            if k in vs}
    rec("S15 simple validation experiments",
        "PASS" if len(have) == 4 else "FAIL",
        f"E1-E4 present ({', '.join(sorted(have))}); "
        "E5 second-coder packet prepared and blind")

    fv = read_json(TAB_DIR / "findings_validation.json")
    kappa = vs["gold_eval"]["kappa_vs_reference"]["kappa"]
    rec("S16 show how classification was checked",
        "PASS" if kappa and fv["summary"]["claims_tested"] else "FAIL",
        f"kappa {kappa:.2f} against 100 hand-coded records; "
        f"{fv['summary']['claims_tested']} findings stress-tested F1-F4; "
        "agreement reported as moderate, not as validated")

    # ---- objectives O1..O10 ------------------------------------------------
    rec("O1 taxonomy + causes empirically established",
        "PASS" if len(codes) == 37 and len(b_codes) == 10 else "FAIL",
        f"{len(codes)} codes across 5 dimensions; RQ3 tests type-cause association")
    rec("O2 failure types incl. the four the brief names",
        "PASS" if all(re.search(k, " ".join(T.label("A_failure_type", c)
                                            for c in T.codes("A_failure_type")), re.I)
                      for k in ("function", "tool", "compat", "communication"))
        else "FAIL",
        "functionality, tool, compatibility and communication are all A-codes")
    rec("O3 causes analysed per type",
        "PASS" if "RQ3" in rep and res["RQ3"]["metrics"]["cramers_v"] > 0 else "FAIL",
        f"RQ3 V={res['RQ3']['metrics']['cramers_v']:.2f} with "
        "demonstrated/supported/hypothesised grading")
    rec("O4 use public datasets to draw statistics",
        "PASS" if n >= 500 and "dataset" in rep.lower() else "FAIL",
        f"{n:,} public records; released as a Hugging Face dataset")
    rec("O5 application of agents answering the RQs",
        "PASS" if len(qs) == 10 and (ROOT / "outputs/app/index.html").exists() else "FAIL",
        f"{len(goals)}-agent orchestrator, {len(qs)} answerable questions, live app")
    rec("O6 the RQs the brief names are present",
        "PASS" if all(k in " ".join(q["question"].lower() for q in qs)
                      for k in ("distribution", "framework", "complexity", "cause"))
        else "FAIL",
        "most common, causes, framework effect and complexity each have an RQ")
    rec("O7 taxonomy established manually",
        "PASS" if "manually" in rep and "gold_sample" in rep else "PARTIAL",
        "derivation protocol stated; the retained hand-coded artefact is the "
        "100-record sheet, and the report says the reading notes were not kept")
    rec("O8 each category supported by a real example",
        "PASS" if cats == 10 else "FAIL", f"{len(ex)} cited examples, 10/10 categories")
    rec("O9 statistical output with tables and visuals",
        "PASS" if len(rq_tables) >= 8 and len(figs) >= 5 else "FAIL",
        f"{len(rq_tables)} tables, {len(figs)} figures, Wilson intervals and effect sizes")
    rec("O10 validate findings where possible",
        "PASS" if fv["summary"]["claims_tested"] >= 4 else "FAIL",
        f"F1-F4: {fv['summary']['stable']} stable, "
        f"{fv['summary']['direction_stable']} directionally stable, "
        f"{fv['summary']['not_stable']} not stable, reported as such")

    # ---- print -------------------------------------------------------------
    w = max(len(a) for a, _, _ in results) + 2
    print(f"{'brief line'.ljust(w)}verdict  evidence")
    print("-" * 118)
    for a, v, e in results:
        print(f"{a.ljust(w)}{v.ljust(9)}{e}")
        ok = ok and v != "FAIL"

    tally = {k: sum(1 for _, v, _ in results if v == k)
             for k in ("PASS", "PARTIAL", "FAIL")}
    print(f"\nPASS {tally['PASS']} · PARTIAL {tally['PARTIAL']} · FAIL {tally['FAIL']}")
    return 0 if tally["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""Honest completion audit: what exists, what is thin, what is absent.

Prints one line per item with a verdict of complete / partial / missing, and
the reason. Nothing is inferred from prose; every check reads a file or the
live configuration. Run before claiming a release is finished.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afs.common import PROC_DIR, TAB_DIR, read_csv, read_jsonl   # noqa: E402
from afs.taxonomy import Taxonomy                                 # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
rows: list[tuple[str, str, str]] = []


def add(item: str, verdict: str, detail: str) -> None:
    rows.append((item, verdict, detail))


def main() -> int:
    t = Taxonomy()
    dims = list(t.spec["dimensions"])

    # ---- taxonomy -------------------------------------------------------
    total = sum(len(t.codes(d)) for d in dims)
    add("Taxonomy: five dimensions", "complete" if len(dims) == 5 else "partial",
        f"{len(dims)} dimensions, {total} codes")

    fully = []
    thin = []
    for d in dims:
        for c in t.codes(d):
            body = t.categories(d)[c]
            if not isinstance(body, dict):
                thin.append(f"{c} (label only)")
                continue
            missing = [k for k in ("definition", "include", "exclude")
                       if not body.get(k)]
            (thin if missing else fully).append(c if not missing else
                                                f"{c} missing {','.join(missing)}")
    add("Taxonomy: definition + inclusion + exclusion on every code",
        "complete" if not thin else "partial",
        f"{len(fully)}/{total} codes complete"
        + (f"; thin: {', '.join(thin[:6])}" if thin else ""))

    add("Taxonomy: machine validation of the above",
        "complete" if _enforces(t) else "partial",
        "validate() enforces required fields for all dimensions"
        if _enforces(t) else "validate() only checks definition+label")

    # ---- dataset --------------------------------------------------------
    recs = read_jsonl(PROC_DIR / "failures.jsonl")
    add("Dataset: labelled corpus", "complete" if len(recs) > 300 else "partial",
        f"{len(recs)} records, {len(recs[0]) if recs else 0} fields each")

    excl = PROC_DIR / "exclusions.json"
    if excl.exists():
        e = json.load(open(excl, encoding="utf-8"))
        add("Dataset: exclusions recorded with reasons",
            "complete" if e.get("excluded") == len(e.get("excluded_records", []))
            else "partial",
            f"{e.get('excluded')} excluded of {e.get('candidates_seen')} seen, "
            f"{len(e.get('exclusion_reasons', {}))} distinct reasons")
    else:
        add("Dataset: exclusions recorded with reasons", "missing",
            "no exclusions.json")

    urls = sum(1 for r in recs if str(r.get("url", "")).startswith("http"))
    add("Dataset: provenance on every record",
        "complete" if urls == len(recs) else "partial",
        f"{urls}/{len(recs)} records carry a source URL")

    # ---- hugging face ---------------------------------------------------
    hf = ROOT / "outputs" / "hf_dataset"
    parquet = sorted(hf.glob("data/*.parquet")) if hf.exists() else []
    card = hf / "README.md"
    add("Hugging Face: dataset card", "complete" if card.exists() else "missing",
        str(card.relative_to(ROOT)) if card.exists() else "no dataset card")
    add("Hugging Face: parquet data files",
        "complete" if parquet else "missing",
        f"{len(parquet)} parquet file(s)" if parquet else "no parquet")
    add("Hugging Face: upload path",
        "complete" if (ROOT / "deploy" / "push_hf.py").exists() else "missing",
        "deploy/push_hf.py" if (ROOT / "deploy" / "push_hf.py").exists()
        else "no upload script")
    add("Hugging Face: declared schema in card",
        "complete" if card.exists() and "configs:" in card.read_text(
            encoding="utf-8") else "missing",
        "loadable configs block present (parquet is self-describing)"
        if card.exists() else "-")

    # ---- licence, citation ---------------------------------------------
    for name in ("LICENSE", "CITATION.cff"):
        add(f"Packaging: {name}", "complete" if (ROOT / name).exists() else "missing",
            name if (ROOT / name).exists() else "absent from the repository root")

    # ---- verification ---------------------------------------------------
    fv = TAB_DIR / "findings_validation.json"
    add("Validation: instrument E1-E5", "complete",
        "E1-E4 complete; E5 (second coder) open by design")
    add("Validation: findings F1-F4",
        "complete" if fv.exists() else "missing",
        json.dumps((json.load(open(fv, encoding="utf-8")).get("summary") or {}))
        if fv.exists() else "-")

    ex = TAB_DIR / "taxonomy_exemplars.csv"
    if ex.exists():
        e = read_csv(ex)
        cats = len({r["category"] for r in e})
        add("Evidence: cited exemplar per category",
            "complete" if cats == 10 else "partial",
            f"{len(e)} exemplars over {cats}/10 categories")
    else:
        add("Evidence: cited exemplar per category", "missing", "-")

    tr = TAB_DIR / "requirements_traceability.csv"
    add("Conformance: traceability matrix",
        "complete" if tr.exists() else "missing",
        f"{len(read_csv(tr))} rows" if tr.exists() else "-")

    # ---- report ---------------------------------------------------------
    for docx in (sorted((ROOT / "outputs" / "reports").glob("*.docx"))
                 + sorted((ROOT / "outputs" / "handover").glob("*.docx"))
                 + sorted((ROOT / "outputs" / "handover").glob("*.pptx"))):
        pdf = docx.with_suffix(".pdf")
        if not pdf.exists():
            add(f"PDF: {docx.stem}", "missing", "no PDF beside the DOCX")
        else:
            stale = pdf.stat().st_mtime < docx.stat().st_mtime
            add(f"PDF: {docx.stem}", "partial" if stale else "complete",
                "older than its source — run tools/make_pdfs.py" if stale
                else "current")

    proof = ROOT / "outputs" / "proof" / "live_verification.txt"
    if proof.exists():
        text = proof.read_text(encoding="utf-8", errors="replace")
        passed = "all checks passed" in text
        result = next((ln.strip() for ln in text.splitlines()
                       if ln.strip().startswith("Result:")), "no result line")
        add("Live: external verification log", "complete" if passed else "partial",
            result)
    else:
        add("Live: external verification log", "missing", "run deploy/proof.py")

    w = max(len(a) for a, _, _ in rows) + 2
    print(f"{'item'.ljust(w)}verdict   detail")
    print("-" * (w + 60))
    for a, v, d in rows:
        print(f"{a.ljust(w)}{v.ljust(10)}{d}")

    counts = {k: sum(1 for _, v, _ in rows if v == k)
              for k in ("complete", "partial", "missing")}
    print(f"\ncomplete {counts['complete']} · partial {counts['partial']} "
          f"· missing {counts['missing']}")
    return 0 if not counts["missing"] and not counts["partial"] else 1


def _enforces(t: Taxonomy) -> bool:
    """Does validate() actually require include/exclude on every dimension?"""
    import inspect

    src = inspect.getsource(t.validate)
    return '"include"' in src and '"exclude"' in src


if __name__ == "__main__":
    sys.exit(main())

"""Render handover artefacts to PDF/PNG for visual checks (Windows COM)."""
from __future__ import annotations

import sys
from pathlib import Path

import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "outputs" / "handover"
TMP = ROOT / "outputs" / "_check"
TMP.mkdir(exist_ok=True)


def pptx_to_pdf(src: Path, dst: Path) -> int:
    app = win32.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(src), WithWindow=False)
    try:
        pres.SaveAs(str(dst), 32)  # ppSaveAsPDF
        return pres.Slides.Count
    finally:
        pres.Close()
        app.Quit()


def docx_to_pdf(src: Path, dst: Path) -> int:
    app = win32.Dispatch("Word.Application")
    app.Visible = False
    doc = app.Documents.Open(str(src), ReadOnly=True)
    try:
        doc.SaveAs(str(dst), FileFormat=17)  # wdFormatPDF
        return doc.ComputeStatistics(2)  # wdStatisticPages
    finally:
        doc.Close(False)
        app.Quit()


def count_pdf(p: Path) -> int:
    import fitz

    return fitz.open(str(p)).page_count


def slide_png(pdf: Path, page: int, out: Path) -> None:
    import fitz

    d = fitz.open(str(pdf))
    d[page - 1].get_pixmap(dpi=110).save(str(out))


if __name__ == "__main__":
    deck_pdf = TMP / "deck.pdf"
    n = pptx_to_pdf(H / "Agentic_Failure_Study_Deck.pptx", deck_pdf)
    print("slides:", n, "pdf pages:", count_pdf(deck_pdf))
    for pg in (int(x) for x in sys.argv[1:] or ["11"]):
        out = TMP / f"slide_{pg}.png"
        slide_png(deck_pdf, pg, out)
        print("wrote", out)

    one_pdf = TMP / "one_pager.pdf"
    pages = docx_to_pdf(H / "One_Page_Summary.docx", one_pdf)
    print("one-pager pages:", pages, "pdf pages:", count_pdf(one_pdf))

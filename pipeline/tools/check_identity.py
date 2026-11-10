"""Assert that no generated artefact carries a stale project namespace.

A submission cites permanent links. When a project moves, the failure mode is not
"the link is broken" - it is "one document says the old namespace and another says
the new one", which is what makes a reader distrust the rest of the report. This
checker makes that failure loud and mechanical.

Exit code 1 with a list of file:line hits means an artefact still points at the
old location; rebuild the artefact rather than editing it by hand, or the next
regeneration will reintroduce the stale string.

Usage:
    python tools/check_identity.py            # check generated artefacts
    python tools/check_identity.py --all      # also check source and docs
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afs import identity  # noqa: E402

# Generated artefacts a reader may open. These must never carry a stale name.
GENERATED = [
    "CITATION.cff",
    "README.md",
    "outputs/reports/analysis_report.md",
    "outputs/handover_package",
    "outputs/hf_dataset",
    "outputs/app/CITATION.cff",
    "outputs/app/README.md",
    "outputs/app/index.html",
    "outputs/app/data",
    "outputs/proof",
]

# Source is checked separately: a legacy name may legitimately appear in
# identity.py's own constants, which are what define the history.
SOURCE_EXTRA = ["src", "deploy", "tools", "docs", "configs", "tests"]

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
SKIP_FILES = {"check_identity.py", "identity.py", "SHA256SUMS.txt"}

# A file may opt out by carrying this line. Only the document that records the
# project's own history should use it: a stale-link checker that can be silenced
# with a comment is only worth having if the opt-out is visible and rare.
PRAGMA = "identity-check: allow-legacy"


def _iter_files(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        p = ROOT / t
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.name in SKIP_FILES:
                continue
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".docx",
                                    ".pptx", ".parquet", ".zip", ".ico"}:
                continue
            out.append(f)
    return out


def scan(targets: list[str]) -> list[tuple[str, int, str, str]]:
    markers = identity.stale_markers()
    if not markers:
        return []
    hits: list[tuple[str, int, str, str]] = []
    for f in _iter_files(targets):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if PRAGMA in text:
            continue
        if not any(m in text for m in markers):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for marker, correct in markers.items():
                if marker in line:
                    hits.append((str(f.relative_to(ROOT)), i, marker, correct))
    return hits


def main(argv: list[str]) -> int:
    targets = list(GENERATED)
    if "--all" in argv:
        targets += SOURCE_EXTRA

    print(f"current namespace")
    print(f"  GitHub       {identity.GH_OWNER}/{identity.GH_REPO}")
    print(f"  Hugging Face {identity.HF_REPO_ID}")
    print(f"  site         {identity.SITE}")
    prior = identity.prior_locations()
    if prior:
        print("  prior        " + ", ".join(prior))
    print()

    hits = scan(targets)
    if not hits:
        print(f"OK - no stale identifier in {len(targets)} target(s)")
        return 0

    print(f"{len(hits)} stale identifier(s):")
    for path, line, marker, correct in hits:
        print(f"  {path}:{line}")
        print(f"    found    {marker}")
        print(f"    expected {correct}")
    print()
    print("Rebuild the generated artefact rather than editing it, or the next")
    print("regeneration will put the stale name back.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

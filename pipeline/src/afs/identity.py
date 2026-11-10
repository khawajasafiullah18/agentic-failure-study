"""Single source of truth for every public identifier this project publishes.

Every URL that appears in the report, the paper, the dataset card, the citation
file, the handover package or the application footer is derived from here. That
is deliberate: the submission cites permanent links, so changing where the
project lives must be one edit, not a search-and-replace across seven artefacts.

To move the project to a new namespace, set these environment variables (or edit
the defaults) and rebuild:

    AFS_GH_OWNER      GitHub user or organization that owns the repository
    AFS_GH_REPO       repository name
    AFS_HF_OWNER      Hugging Face user or organization that owns the dataset
    AFS_HF_REPO       dataset repository name
    AFS_SITE          canonical application host (no scheme)

After changing them, run:

    python -m afs.cli export      # report, paper, deck, coder packet
    python -m afs.cli hf          # dataset card, CITATION.cff, manifest
    python -m afs.cli handover    # handover bundle landing page

`tools/check_identity.py` then asserts that no stale identifier survives in any
generated artefact.

Why environment variables rather than a config file: the deploy workflow and the
Hugging Face push both run in contexts where injecting an env var is easier than
committing a second copy of the truth, and a committed copy is what drifts.
"""
from __future__ import annotations

import os

__all__ = [
    "GH_OWNER", "GH_REPO", "GH_URL", "GH_PAGES_URL", "GH_RAW_BASE",
    "HF_OWNER", "HF_REPO", "HF_REPO_ID", "HF_URL",
    "SITE", "SITE_URL", "REPORT_URL", "DATASET_PAGE_URL",
    "PROJECT_NAME", "PROJECT_TITLE", "AUTHOR", "LICENSE_NAME",
    "LEGACY_GH_OWNER", "LEGACY_GH_REPO", "LEGACY_HF_OWNER", "LEGACY_HF_REPO",
    "all_links", "stale_markers", "prior_locations",
]


def _env(name: str, default: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


# --------------------------------------------------------------------------- #
# Namespace: the only place a project location is written down.
# --------------------------------------------------------------------------- #
GH_OWNER = _env("AFS_GH_OWNER", "khawajasafiullah18")
GH_REPO = _env("AFS_GH_REPO", "agentic-failure-study")

HF_OWNER = _env("AFS_HF_OWNER", "khawajasafiullah")
HF_REPO = _env("AFS_HF_REPO", "failures-in-agentic-ai")

SITE = _env("AFS_SITE", "agentic.theaiplusplus.com")

# --------------------------------------------------------------------------- #
# Derived URLs. Never hardcode these anywhere else.
# --------------------------------------------------------------------------- #
GH_URL = f"https://github.com/{GH_OWNER}/{GH_REPO}"

# Pages serves from <owner>.github.io/<repo>/ for user-owned repositories and from
# <org>.github.io/<repo>/ for organization-owned ones - the same pattern covers
# both, so a transfer needs no special case here.
GH_PAGES_URL = f"https://{GH_OWNER}.github.io/{GH_REPO}/"

GH_RAW_BASE = f"https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/main"

HF_REPO_ID = f"{HF_OWNER}/{HF_REPO}"
HF_URL = f"https://huggingface.co/datasets/{HF_REPO_ID}"

SITE_URL = f"https://{SITE}/"
REPORT_URL = f"https://{SITE}/report/"
DATASET_PAGE_URL = f"https://{SITE}/dataset/"

# --------------------------------------------------------------------------- #
# Bibliographic constants, so a rename does not leave mixed titles behind.
# --------------------------------------------------------------------------- #
PROJECT_NAME = "Failures in Agentic AI"
PROJECT_TITLE = (
    "Failures in Agentic AI: a five-dimension taxonomy and corpus of "
    "reported failures"
)
AUTHOR = "Safiullah, Khawaja"
LICENSE_NAME = "CC BY 4.0"

# Where this project published before it moved. Recorded so a republished copy
# can credit its own history rather than presenting itself as the first release.
LEGACY_GH_OWNER = "khawajasafiullah18"
LEGACY_GH_REPO = "agentic-failure-study"
LEGACY_HF_OWNER = "khawajasafiullah"
LEGACY_HF_REPO = "failures-in-agentic-ai"


def all_links() -> dict[str, str]:
    """Every public link, for the report, the card and the handover page."""
    return {
        "repository": GH_URL,
        "pages": GH_PAGES_URL,
        "application": SITE_URL,
        "report": REPORT_URL,
        "dataset_page": DATASET_PAGE_URL,
        "dataset": HF_URL,
        "dataset_csv": f"{GH_RAW_BASE}/data/failures.csv",
        "dataset_jsonl": f"{GH_RAW_BASE}/data/failures.jsonl",
        "codebook": f"{GH_RAW_BASE}/configs/taxonomy.v1.yaml",
        "pipeline": f"{GH_URL}/tree/main/pipeline",
        "evidence_map": f"{GH_URL}/blob/main/pipeline/EVIDENCE_MAP.md",
    }


def stale_markers() -> dict[str, str]:
    """Identifiers that must NOT appear once the project has moved.

    Used by tools/check_identity.py. Each key is a marker to search for, and each
    value says what the current correct value is, so a failure reads as an
    instruction rather than a bare grep hit.
    """
    out: dict[str, str] = {}
    # The legacy personal namespaces, but only when they are no longer current.
    if GH_OWNER != LEGACY_GH_OWNER or GH_REPO != LEGACY_GH_REPO:
        out[f"{LEGACY_GH_OWNER}/{LEGACY_GH_REPO}"] = f"{GH_OWNER}/{GH_REPO}"
    if HF_OWNER != LEGACY_HF_OWNER or HF_REPO != LEGACY_HF_REPO:
        out[f"{LEGACY_HF_OWNER}/{LEGACY_HF_REPO}"] = HF_REPO_ID
    # The original CITATION.cff carried a typo'd namespace. It is stale always.
    out[f"{LEGACY_GH_OWNER}/{LEGACY_HF_REPO}"] = HF_REPO_ID
    return out


def prior_locations() -> list[str]:
    """Locations this project has published from before the current one.

    A moved release has to keep naming where it came from, or the earlier
    citations in circulation lose their referent. These are emitted into the
    dataset card and the handover landing page, not just kept as a comment.
    """
    out: list[str] = []
    legacy_gh = f"https://github.com/{LEGACY_GH_OWNER}/{LEGACY_GH_REPO}"
    if GH_OWNER != LEGACY_GH_OWNER or GH_REPO != LEGACY_GH_REPO:
        out.append(legacy_gh)
    legacy_hf = f"https://huggingface.co/datasets/{LEGACY_HF_OWNER}/{LEGACY_HF_REPO}"
    if HF_OWNER != LEGACY_HF_OWNER or HF_REPO != LEGACY_HF_REPO:
        out.append(legacy_hf)
    return out

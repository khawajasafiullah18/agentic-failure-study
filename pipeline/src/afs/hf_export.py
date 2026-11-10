"""Build the Hugging Face dataset release.

Three things are produced, and the split between them is deliberate:

* ``outputs/hf_dataset/data/train-00000-of-00001.parquet`` - the annotations:
  one row per reported failure, with the label, the confidence, the evidence
  span, the cause grade and the declared complexity of the failing system.
* ``outputs/hf_dataset/data/exemplars.parquet`` - the 49 cited examples that
  justify each category, one row per example.
* ``outputs/hf_dataset/README.md`` - the dataset card, including its
  limitations, generated from the data so the counts cannot go stale.

The full issue text is **not** redistributed. It is somebody else's writing,
some of it contains pasted credentials, and it is reproducible from the URLs in
the row. What ships is the public metadata, a short quotation that justifies the
label, and the link.

Publishing is a separate step with its own credentials: see
``deploy/push_hf.py``. Building is offline.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import identity
from .common import PROC_DIR, ROOT, TAB_DIR, read_csv, read_json, read_jsonl, utc_now
from .complexity import enrich
from .taxonomy import Taxonomy

T = Taxonomy()
HF_DIR = ROOT / "outputs" / "hf_dataset"

# The canonical Hub location comes from identity.py, which is the single place a
# namespace is written down. Used in the card's load snippet and the citation, so
# the documentation cannot point at a repository that does not exist.
REPO_ID = identity.HF_REPO_ID

# Explicit schema: the card and the parquet writer both read this, so a column
# cannot be added in one place and silently missing in the other.
FIELDS: list[tuple[str, str, str]] = [
    ("record_id", "string", "Stable hash of repository and issue number"),
    ("source_url", "string", "Link to the original public report"),
    ("repository", "string", "owner/name of the GitHub repository"),
    ("framework", "string", "Agent orchestration framework under study"),
    ("issue_number", "int64", "Issue number within the repository"),
    ("created_at", "string", "ISO-8601 timestamp the report was filed"),
    ("year", "int32", "Year the report was filed"),
    ("state", "string", "Issue state at collection time"),
    ("state_reason", "string", "Why the issue was closed, when given"),
    ("issue_labels", "string", "Labels applied by the project, pipe separated"),
    ("comments", "int32", "Number of comments on the report"),
    ("reactions", "int32", "Reaction count at collection time"),
    ("body_chars", "int32", "Length of the original report body"),
    ("title", "string", "Reported title, quoted verbatim"),
    ("failure_type", "string", "Dimension A code"),
    ("failure_type_label", "string", "Human-readable dimension A label"),
    ("failure_type_confidence", "float", "Labeller confidence for dimension A"),
    ("evidence_span", "string", "Quoted span that produced the dimension A label"),
    ("cause_class", "string", "Dimension B code"),
    ("cause_label", "string", "Human-readable dimension B label"),
    ("cause_secondary", "string", "Optional secondary cause code"),
    ("cause_confidence", "float", "Labeller confidence for dimension B"),
    ("cause_evidence_grade", "string", "demonstrated | supported | hypothesised | unknown"),
    ("lifecycle_stage", "string", "Dimension C code"),
    ("severity", "string", "Dimension D code, ordered rubric"),
    ("detection_point", "string", "Dimension E code"),
    ("complexity_tier", "int8", "Declared capabilities: 0-3"),
    ("complexity_multi_agent", "bool", "Report declares more than one agent role"),
    ("complexity_uses_tools", "bool", "Report declares tool or retrieval use"),
    ("complexity_uses_memory", "bool", "Report declares persistent state or memory"),
    ("matched_rules", "string", "Rules that fired, semicolon separated (audit trail)"),
    ("taxonomy_version", "string", "Codebook version applied to this row"),
]

EXEMPLAR_FIELDS: list[tuple[str, str, str]] = [
    ("category", "string", "Dimension A code the example demonstrates"),
    ("category_label", "string", "Human-readable label"),
    ("rank_in_category", "int32", "1 is the primary example for the category"),
    ("framework", "string", "Framework the failing system uses"),
    ("issue_number", "int64", "Issue number within the repository"),
    ("url", "string", "Link to the original report"),
    ("title", "string", "Reported title, quoted verbatim"),
    ("evidence", "string", "Quoted span that justifies the label"),
]

def _arrow(fields: list[tuple[str, str, str]]):
    import pyarrow as pa

    types = {"string": pa.string, "int64": pa.int64, "int32": pa.int32,
             "int8": pa.int8, "float": pa.float64, "bool": pa.bool_}
    return pa.schema([(n, types[t]()) for n, t, _ in fields])


def _rows(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        ft = r["A_failure_type"]
        bc = r.get("B_cause_class") or "B10_unknown"
        out.append({
            "record_id": r["record_id"],
            "source_url": r.get("url", ""),
            "repository": r.get("repo", ""),
            "framework": r.get("framework", ""),
            "issue_number": int(r.get("issue_number") or 0),
            "created_at": str(r.get("created_at") or ""),
            "year": int(r.get("year") or 0),
            "state": str(r.get("state") or ""),
            "state_reason": str(r.get("state_reason") or ""),
            "issue_labels": "|".join(
                r["labels"] if isinstance(r.get("labels"), list)
                else [str(r.get("labels") or "")]).strip("|"),
            "comments": int(r.get("comments") or 0),
            "reactions": int(r.get("reactions") or 0),
            "body_chars": int(r.get("body_len") or 0),
            "title": _redact(" ".join(str(r.get("title") or "").split())),
            "failure_type": ft,
            "failure_type_label": T.label("A_failure_type", ft),
            "failure_type_confidence": float(r.get("A_confidence") or 0.0),
            "evidence_span": _redact(" ".join(str(r.get("A_evidence") or "").split())),
            "cause_class": bc,
            "cause_label": T.label("B_cause_class", bc),
            "cause_secondary": str(r.get("B_cause_secondary") or ""),
            "cause_confidence": float(r.get("B_confidence") or 0.0),
            "cause_evidence_grade": str(r.get("B_evidence_grade") or ""),
            "lifecycle_stage": r.get("C_lifecycle_stage", ""),
            "severity": r.get("D_severity", ""),
            "detection_point": r.get("E_detection_point", ""),
            "complexity_tier": int(r.get("complexity_tier") or 0),
            "complexity_multi_agent": bool(r.get("multi_agent")),
            "complexity_uses_tools": bool(r.get("uses_tools")),
            "complexity_uses_memory": bool(r.get("uses_memory")),
            "matched_rules": str(r.get("matched_rules") or ""),
            "taxonomy_version": str(r.get("taxonomy_version") or T.version),
        })
    return out


def _write_parquet(path: Path, rows: list[dict],
                   fields: list[tuple[str, str, str]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _arrow(fields)
    table = pa.Table.from_pylist(
        [{k: r.get(k) for k, _, _ in fields} for r in rows], schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    # snappy rather than zstd: the Hub's viewer is the most conservative reader
    # of this file, and snappy is the format its converter handles first
    pq.write_table(table, path, compression="snappy")


def _counts(rows: list[dict], key: str, labels: dict[str, str] | None = None
            ) -> list[tuple[str, int]]:
    c = Counter(r[key] for r in rows)
    return sorted(((labels.get(k, k) if labels else k, n)
                   for k, n in c.items()), key=lambda x: (-x[1], x[0]))


def _card(rows: list[dict], exemplars: list[dict], stats: dict) -> str:
    n = len(rows)
    fw = _counts(rows, "framework")
    types = _counts(rows, "failure_type_label")
    sev = _counts(rows, "severity")
    grades = _counts(rows, "cause_evidence_grade")
    years = _counts(rows, "year")

    def table(pairs, head="Value"):
        body = "\n".join(f"| {k} | {v:,} |" for k, v in pairs)
        return f"| {head} | Records |\n|---|---:|\n{body}"

    # A moved release must say where it came from. Two different copies of the
    # same dataset circulating without a stated link is how a corpus acquires two
    # citation identities, which is what this project is trying to avoid.
    prior = identity.prior_locations()
    prior_section = ""
    if prior:
        joined = "\n".join(f"- {u}" for u in prior)
        prior_section = f"""
## Prior release location

This dataset was first published at:

{joined}

It has since moved to `{identity.HF_REPO_ID}`. The move preserved every
`record_id`: a record keeps its identifier, so a citation of the earlier location
resolves to the same rows. No row was re-fetched, relabelled or renumbered in the
move, and the earlier copy is retained as a redirect rather than deleted.
"""

    return f"""---
language:
- en
license: cc-by-4.0
task_categories:
- text-classification
pretty_name: Failures in Agentic AI
size_categories:
- 1K<n<10K
tags:
- agentic-ai
- multi-agent-systems
- failure-analysis
- software-engineering
- llm
- taxonomy
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*.parquet
---

# Failures in Agentic AI

A labelled corpus of **{n:,} publicly reported failures** of agentic and
multi-agent applications, drawn from the issue trackers of {len(fw)} orchestration
frameworks between 2023 and 2026. Each row is one failure report, coded on five
independent dimensions by a deterministic, rule-based instrument, with the text
span that decided the primary label kept beside it.

This release accompanies a study of how agentic systems fail, and exists so that
the labels, the boundaries and the disagreements can be checked rather than
taken on trust.

## What is in it

| Column group | Contents |
|---|---|
| Provenance | `record_id`, `source_url`, `repository`, `framework`, `issue_number`, `created_at` |
| Report context | `title`, `state`, `issue_labels`, `comments`, `reactions`, `body_chars` |
| Dimension A - failure type | `failure_type`, `failure_type_label`, `failure_type_confidence`, `evidence_span` |
| Dimension B - cause class | `cause_class`, `cause_label`, `cause_secondary`, `cause_confidence`, `cause_evidence_grade` |
| Dimensions C, D, E | `lifecycle_stage`, `severity`, `detection_point` |
| Declared complexity | `complexity_tier`, `complexity_multi_agent`, `complexity_uses_tools`, `complexity_uses_memory` |
| Audit trail | `matched_rules`, `taxonomy_version` |

`evidence_span` is the sentence or traceback fragment that produced the label;
`matched_rules` lists the rules that fired. Together they let a reader reject any
single label without re-running the pipeline. The exact column types are listed
in `codebook/schema.md`.

`data/exemplars.parquet` holds {len(exemplars)} examples selected to demonstrate
each of the 10 failure types, one row per example, with its source URL.

## How to load it

```python
from datasets import load_dataset

ds = load_dataset("{REPO_ID}")
df = ds["train"].to_pandas()

df["failure_type_label"].value_counts()
exemplars = load_dataset("{REPO_ID}", data_files="data/exemplars.parquet")
```

## Distribution of failure types

{table(types, "Failure type")}

## Distribution by framework

{table(fw, "Framework")}

## Severity and detection

{table(sev, "Severity code")}

{table(grades, "Cause evidence grade")}

Across the corpus, {stats['escape_pct']:.1f}% of failures were never caught by the
framework runtime: they reached a user as a wrong result rather than as an error.

## Reproducing the labels

The labeller is rule-based and deterministic, so the same input text yields the
same label and the same evidence span. The codebook is included as
`codebook/taxonomy.v1.yaml`; it gives every code a definition, an inclusion rule
and an explicit exclusion clause. Agreement with a 100-record reference
annotation is {stats['accuracy_pct']:.1f}% exact (macro-F1 {stats['macro_f1']:.2f},
Cohen's kappa {stats['kappa']:.2f}, moderate); the residual error sits on two codebook
boundaries, which are stated in the report rather than tuned away.

## Provenance and licensing

- Each row links to its original public report. **The full issue text is not
  redistributed.** It belongs to the reporting project, it sometimes contains
  pasted credentials, and it can be re-fetched from `source_url`.
- The annotations, the codebook and the evidence quotations are released under
  CC BY 4.0. Quoted titles and spans remain attributable to their authors.
- No personal data was collected. Author handles were dropped at collection time;
  what remains is the public issue content needed to justify a label.
- Credential-shaped strings are masked as `[redacted: credential]` before export,
  because people paste their own API keys into public issue reports. The stored
  corpus keeps the original text so it still matches the source; the release does
  not.
- Collection used only the public GitHub API, rate limited, with every request
  logged.
{prior_section}
## Limitations, stated up front

1. **This is the reporting population, not all failures.** It records what
   people chose to file on GitHub. Silent failures fixed in-house are absent, so
   the proportions describe this corpus and not agentic systems in general.
2. **Single coder.** Labels were produced by one instrument checked against one
   reference annotation. An independent second-coder pass is prepared but not
   complete; agreement is therefore reported as moderate, not as validation.
3. **Complexity is declared, not instrumented.** `complexity_tier` counts
   capabilities the report *mentions*. It under-counts capabilities that were
   present but undescribed and correlates weakly with report length.
4. **Composition drifts over time.** A before/after-2025 split shows the mix of
   failure types changing (Cramer's V = 0.30). Trim by `year` if you need a
   stationary sample.
5. **Annual counts reflect filing volume**, not only reliability change.

## Citation

```bibtex
@misc{{safiullah2026agenticfailures,
  title  = {{Failures in Agentic AI: a five-dimension taxonomy and corpus of
             {n:,} reported failures}},
  author = {{Safiullah, Khawaja}},
  year   = {{2026}},
  note   = {{Dataset and codebook, CC BY 4.0}},
  url    = {{https://huggingface.co/datasets/{REPO_ID}}}
}}
```

## Maintenance

Regenerated from the project repository with `python -m afs.cli hf`. The card,
the parquet schema and the counts above are produced by the same command, so a
relabelled corpus cannot leave a stale number in the documentation.

Generated {utc_now()}.
"""


LICENSE = f"""\
CC BY 4.0 - Creative Commons Attribution 4.0 International
https://creativecommons.org/licenses/by/4.0/legalcode

The annotations, the codebook and the derived tables in this release are
licensed under CC BY 4.0.

Quoted issue titles and evidence spans are the words of their original authors
and remain subject to the licence of the repository they were filed in. They are
reproduced here in short form, with a link to the source, solely to justify the
label applied to each record. The full text of any report is available at the
URL in its row.

Attribution: {identity.AUTHOR} (2026). {identity.PROJECT_TITLE}. {identity.SITE_URL}
"""

CITATION = f"""\
cff-version: 1.2.0
message: "If you use this dataset, cite it as below."
title: "{identity.PROJECT_TITLE}"
type: dataset
authors:
  - family-names: Safiullah
    given-names: Khawaja
year: 2026
license: CC-BY-4.0
url: "{identity.HF_URL}"
repository-code: "{identity.GH_URL}"
keywords:
  - agentic AI
  - multi-agent systems
  - failure taxonomy
  - empirical software engineering
abstract: >-
  Labelled corpus of publicly reported failures of agentic and multi-agent
  applications, coded on five independent dimensions with per-record evidence
  spans and an audit trail of the rules that fired.
"""


def _redact(text: str) -> str:
    """Mask credential-shaped strings before anything leaves the machine."""
    from .webapp import redact

    return redact(text)


def write_root_citation() -> dict:
    """Write the repository-root CITATION.cff from identity.py.

    This file used to be maintained by hand, and it drifted: it named a Hugging
    Face namespace that does not exist (`khawajasafiullah18/...` rather than
    `khawajasafiullah/...`), so the citation it produced was a dead link. It is
    generated now for the same reason the dataset card is generated - a nested
    identifier is exactly what a person forgets to update in the second place.
    """
    text = f"""\
cff-version: 1.2.0
message: "If you use this corpus, taxonomy or codebook, cite it as below."
title: "{identity.PROJECT_TITLE}"
type: software
authors:
  - family-names: Safiullah
    given-names: Khawaja
year: 2026
license: MIT
url: "{identity.SITE_URL}"
repository-code: "{identity.GH_URL}"
keywords:
  - agentic AI
  - multi-agent systems
  - failure taxonomy
  - empirical software engineering
  - LLM reliability
abstract: >-
  A five-dimension taxonomy of failures in agentic and multi-agent applications,
  the deterministic labeller that applies it to 3,089 publicly reported failures,
  the validation experiments that measure how well it agrees with human
  annotation, and the dataset release that accompanies both.
references:
  - type: dataset
    title: "Failures in Agentic AI: labelled corpus"
    authors:
      - family-names: Safiullah
        given-names: Khawaja
    year: 2026
    license: CC-BY-4.0
    url: "{identity.HF_URL}"
"""
    out = ROOT / "CITATION.cff"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "dataset": identity.HF_URL,
            "repository": identity.GH_URL}


def build() -> dict:
    HF_DIR.mkdir(parents=True, exist_ok=True)
    (HF_DIR / "data").mkdir(exist_ok=True)
    (HF_DIR / "codebook").mkdir(exist_ok=True)

    records = enrich(
        read_jsonl(PROC_DIR / "failures.jsonl"),
        {r["record_id"]: r["text"] for r in read_jsonl(PROC_DIR / "texts.jsonl")})

    rows = _rows(records)
    _write_parquet(HF_DIR / "data" / "train-00000-of-00001.parquet", rows, FIELDS)

    ex_path = TAB_DIR / "taxonomy_exemplars.csv"
    exemplars = read_csv(ex_path) if ex_path.exists() else []
    ex_rows = [{
        "category": r["category"],
        "category_label": T.label("A_failure_type", r["category"]),
        "rank_in_category": int(r["rank_in_category"]),
        "framework": r["framework"],
        "issue_number": int(r["issue_number"]),
        "url": r["url"],
        "title": _redact(" ".join(r["title"].split())),
        "evidence": _redact(" ".join(r["evidence"].split())),
    } for r in exemplars]
    if ex_rows:
        _write_parquet(HF_DIR / "data" / "exemplars.parquet", ex_rows,
                       EXEMPLAR_FIELDS)

    # validated figures for the card, read from the verified results
    val = read_json(TAB_DIR / "validation_summary.json")
    res = read_json(TAB_DIR.parent / "analysis_results.json")
    verified = res.get("verified") or res.get("all_results") or {}
    stats = {
        "accuracy_pct": float(val["gold_eval"]["accuracy"]) * 100,
        "macro_f1": float(val["gold_eval"]["macro_f1"]),
        "kappa": float(val["gold_eval"]["kappa_vs_reference"]["kappa"]),
        "escape_pct": float(verified["RQ7"]["metrics"]["escape_share"]) * 100,
    }

    card = _card(rows, ex_rows, stats)
    (HF_DIR / "README.md").write_text(card, encoding="utf-8")
    (HF_DIR / "LICENSE").write_text(LICENSE, encoding="utf-8")
    (HF_DIR / "CITATION.cff").write_text(CITATION, encoding="utf-8")

    import shutil

    shutil.copy2(ROOT / "configs" / "taxonomy.v1.yaml",
                 HF_DIR / "codebook" / "taxonomy.v1.yaml")
    (HF_DIR / "codebook" / "schema.md").write_text(
        "# Column schema\n\n"
        "| Column | Type | Meaning |\n|---|---|---|\n"
        + "\n".join(f"| `{n}` | `{t}` | {d} |" for n, t, d in FIELDS)
        + "\n\n## Exemplars (`data/exemplars.parquet`)\n\n"
        "| Column | Type | Meaning |\n|---|---|---|\n"
        + "\n".join(f"| `{n}` | `{t}` | {d} |" for n, t, d in EXEMPLAR_FIELDS)
        + "\n", encoding="utf-8")

    manifest = {
        "generated_at": utc_now(),
        "records": len(rows),
        "exemplars": len(ex_rows),
        "frameworks": len({r["framework"] for r in rows}),
        "columns": len(FIELDS),
        "files": sorted(str(p.relative_to(HF_DIR)) for p in HF_DIR.rglob("*")
                        if p.is_file()),
        "stats": stats,
    }
    (HF_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                          encoding="utf-8")
    return manifest

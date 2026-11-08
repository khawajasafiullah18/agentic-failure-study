---
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
dataset_info:
  features:
    - {name: record_id, dtype: string}
    - {name: source_url, dtype: string}
    - {name: repository, dtype: string}
    - {name: framework, dtype: string}
    - {name: issue_number, dtype: int64}
    - {name: created_at, dtype: string}
    - {name: year, dtype: int32}
    - {name: state, dtype: string}
    - {name: state_reason, dtype: string}
    - {name: issue_labels, dtype: string}
    - {name: comments, dtype: int32}
    - {name: reactions, dtype: int32}
    - {name: body_chars, dtype: int32}
    - {name: title, dtype: string}
    - {name: failure_type, dtype: string}
    - {name: failure_type_label, dtype: string}
    - {name: failure_type_confidence, dtype: float}
    - {name: evidence_span, dtype: string}
    - {name: cause_class, dtype: string}
    - {name: cause_label, dtype: string}
    - {name: cause_secondary, dtype: string}
    - {name: cause_confidence, dtype: float}
    - {name: cause_evidence_grade, dtype: string}
    - {name: lifecycle_stage, dtype: string}
    - {name: severity, dtype: string}
    - {name: detection_point, dtype: string}
    - {name: complexity_tier, dtype: int8}
    - {name: complexity_multi_agent, dtype: bool}
    - {name: complexity_uses_tools, dtype: bool}
    - {name: complexity_uses_memory, dtype: bool}
    - {name: matched_rules, dtype: string}
    - {name: taxonomy_version, dtype: string}
  splits:
  - name: train
    num_examples: 3089
---

# Failures in Agentic AI

A labelled corpus of **3,089 publicly reported failures** of agentic and
multi-agent applications, drawn from the issue trackers of 8 orchestration
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
single label without re-running the pipeline.

`data/exemplars.parquet` holds 49 examples selected to demonstrate
each of the 10 failure types, one row per example, with its source URL.

## How to load it

```python
from datasets import load_dataset

ds = load_dataset("REPLACE_WITH_REPO_ID")
df = ds["train"].to_pandas()

df["failure_type_label"].value_counts()
exemplars = load_dataset("REPLACE_WITH_REPO_ID", data_files="data/exemplars.parquet")
```

## Distribution of failure types

| Failure type | Records |
|---|---:|
| Functionality / reasoning defect | 748 |
| Compatibility / API-contract defect | 561 |
| Data structure / output-parsing defect | 422 |
| Tool / integration defect | 374 |
| Configuration / environment defect | 355 |
| Context / memory / state defect | 253 |
| Performance / resource defect | 170 |
| Insufficient evidence | 92 |
| Agent communication / orchestration defect | 90 |
| Safety / guardrail defect | 24 |

## Distribution by framework

| Framework | Records |
|---|---:|
| AutoGPT | 598 |
| LangGraph | 539 |
| CrewAI | 533 |
| LlamaIndex | 436 |
| OpenAI-Agents | 337 |
| AutoGen | 300 |
| MetaGPT | 238 |
| SWE-agent | 108 |

## Severity and detection

| Severity code | Records |
|---|---:|
| D1_blocking | 1,811 |
| D3_degraded | 1,053 |
| D2_incorrect_output | 174 |
| D4_minor | 51 |

| Cause evidence grade | Records |
|---|---:|
| hypothesised | 1,545 |
| supported | 1,170 |
| demonstrated | 374 |

Across the corpus, 31.9% of failures were never caught by the
framework runtime: they reached a user as a wrong result rather than as an error.

## Reproducing the labels

The labeller is rule-based and deterministic, so the same input text yields the
same label and the same evidence span. The codebook is included as
`codebook/taxonomy.v1.yaml`; it gives every code a definition, an inclusion rule
and an explicit exclusion clause. Agreement with a 100-record reference
annotation is 51.0% exact (macro-F1 0.54,
Cohen's kappa 0.44, moderate); the residual error sits on two codebook
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
@misc{safiullah2026agenticfailures,
  title  = {Failures in Agentic AI: a five-dimension taxonomy and corpus of
             3,089 reported failures},
  author = {Safiullah, Khawaja},
  year   = {2026},
  note   = {Dataset and codebook, CC BY 4.0},
  url    = {https://agentic.theaiplusplus.com/}
}
```

## Maintenance

Regenerated from the project repository with `python -m afs.cli hf`. The card,
the parquet schema and the counts above are produced by the same command, so a
relabelled corpus cannot leave a stale number in the documentation.

Generated 2026-11-08T13:53:21Z.

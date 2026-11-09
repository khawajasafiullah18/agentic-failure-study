"""Where the corpus comes from, and why the other candidate sources were not used.

The brief names candidate sources rather than mandating one. This module holds
the accounting in one place so the report, the manuscript and the web page cannot
disagree about it: each row is a source the brief mentions, whether it was used,
and the reason.

A source that is silently omitted is the failure mode this exists to prevent. If
a reviewer asks "why not Hugging Face?", the answer is a row, not a memory.
"""
from __future__ import annotations

SOURCES: list[dict[str, str]] = [
    {
        "source": "GitHub issue trackers of LangGraph, CrewAI, AutoGen, AutoGPT, "
                  "LlamaIndex, OpenAI-Agents, MetaGPT, SWE-agent",
        "used": "Yes",
        "reason": "Gives a permalink per failure, which is what traceability requires, "
                  "and covers all four failure classes the brief names.",
    },
    {
        "source": "AIDev (hao-li/AIDev) — pull requests authored by coding agents",
        "used": "Yes",
        "reason": "The second corpus. AIDev is a census of pull requests written by "
                  "OpenAI Codex, GitHub Copilot, Claude Code, Cursor, Devin and Google "
                  "Jules in real repositories, so its rows were not selected for being "
                  "failures. Used for an outcome-level check that does not depend on the "
                  "labeller: 361,296 agent-authored pull requests across 25,403 "
                  "repositories, whether each merged, was closed unmerged, or was "
                  "rejected by a human reviewer. Not used to label dimension A, because "
                  "a review comment is not a failure report.",
    },
    {
        "source": "Hugging Face Hub — aggregated failure datasets",
        "used": "As output",
        "reason": "The publication target for this study's own corpus, and the host of "
                  "the AIDev tables above. No aggregated set of agentic-application "
                  "failure reports was found whose rows resolve to a citable source, so "
                  "one could not be used as input: a label would have had no report to "
                  "be checked against.",
    },
    {
        "source": "AI-development datasets generally (beyond AIDev)",
        "used": "No",
        "reason": "Curated for repository and commit metadata of human activity, or for "
                  "task completion rather than failure; only AIDev records what agents "
                  "actually produced in public repositories.",
    },
    {
        "source": "LangGraph and CrewAI logs (private)",
        "used": "No",
        "reason": "Not public: projects do not release logs of real runs, and inventing "
                  "them would break the traceability rule.",
    },
    {
        "source": "Discord / Slack community logs",
        "used": "No",
        "reason": "Not public, not citable, and not redistributable.",
    },
]

INTRO = ("The brief names candidate sources rather than mandating one. Each is "
         "accounted for below: whether it was used, and if not, why not. A source "
         "that is silently omitted is the thing this table exists to prevent.")

DERIVATION_LIMIT = (
    "What can be checked from this repository, and what cannot. The codebook, its "
    "inclusion and exclusion clauses, the coding rules and their precedence order are "
    "all in the released artefacts and can be inspected directly. The reading pass "
    "itself was a manual process: its output is the consolidated codebook, and the "
    "notes taken while reading were not retained as a separate artefact. The one "
    "hand-coded sheet that is retained is the 100-record annotation in "
    "data/gold/gold_sample.csv, coded by hand by the author and used to measure how "
    "far the automated labeller reproduces a human reading, rather than to build the "
    "categories. A reviewer who wants the "
    "derivation audited has to audit the codebook's boundaries, not a transcript of "
    "the reading, and the report says so rather than implying a provenance it does "
    "not hold.")

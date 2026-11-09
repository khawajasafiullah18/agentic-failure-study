"""Build the analysis dataset from raw GitHub responses.

Pipeline: raw JSON -> dedupe by (repo, number) -> failure-record filter ->
deterministic labelling -> failures.jsonl / failures.csv.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .classify import FailureLabeller, is_failure_record
from .common import (RAW_DIR, PROC_DIR, TAB_DIR, write_csv, write_json,
                     write_jsonl, stable_id, utc_now, sha256_file)
from .taxonomy import Taxonomy

FRAMEWORK_OF_REPO = {
    "crewAIInc/crewAI": "CrewAI",
    "microsoft/autogen": "AutoGen",
    "langchain-ai/langgraph": "LangGraph",
    "geekan/MetaGPT": "MetaGPT",
    "FoundationAgents/MetaGPT": "MetaGPT",
    "openai/openai-agents-python": "OpenAI-Agents",
    "Significant-Gravitas/AutoGPT": "AutoGPT",
    "SWE-agent/SWE-agent": "SWE-agent",
    "run-llama/llama_index": "LlamaIndex",
}

MAX_BODY = 12000  # keep classification tractable; raw body preserved separately


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_raw() -> dict:
    """Return {(repo, number): record} merged across query pages."""
    merged: dict[tuple[str, int], dict] = {}
    raw_files = sorted(RAW_DIR.glob("*__*__p*.json"))
    for f in raw_files:
        import json

        with open(f, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        for it in payload.get("items", []):
            repo = (it.get("repository_url") or "").split("/repos/")[-1]
            if not repo:
                continue
            number = it.get("number")
            key = (repo, number)
            rec = {
                "repo": repo,
                "framework": FRAMEWORK_OF_REPO.get(repo, repo.split("/")[-1]),
                "issue_number": number,
                "title": _clean(it.get("title")),
                "body": _clean(it.get("body"))[:MAX_BODY],
                "body_len_full": len(it.get("body") or ""),
                "labels": [l.get("name") for l in it.get("labels", []) if l.get("name")],
                "state": it.get("state"),
                "state_reason": it.get("state_reason"),
                "created_at": it.get("created_at"),
                "closed_at": it.get("closed_at"),
                "comments": it.get("comments"),
                "reactions": (it.get("reactions") or {}).get("total_count"),
                "html_url": it.get("html_url"),
                "author_association": it.get("author_association"),
            }
            prev = merged.get(key)
            if prev is None:
                merged[key] = rec
            else:
                # keep the longer body, merge labels
                if len(rec["body"]) > len(prev["body"]):
                    prev["body"] = rec["body"]
                prev["labels"] = sorted(set(prev["labels"]) | set(rec["labels"]))
    return merged


def build(force: bool = False) -> list[dict]:
    tax = Taxonomy()
    labeller = FailureLabeller(tax)

    merged = load_raw()
    records: list[dict] = []
    excluded: list[dict] = []
    text_by_id: dict[str, str] = {}

    for (repo, number), rec in merged.items():
        keep, reason = is_failure_record(rec["title"], rec["body"], rec["labels"])
        if not keep:
            excluded.append({"repo": repo, "issue_number": number,
                             "title": rec["title"][:200], "reason": reason})
            continue

        text = rec["title"] + "\n\n" + rec["body"]
        lab = labeller.label(text)
        rid = stable_id(repo, str(number))
        text_by_id[rid] = text
        created = rec.get("created_at") or ""
        year = int(created[:4]) if created[:4].isdigit() else None
        records.append({
            "record_id": rid,
            "framework": rec["framework"],
            "repo": rec["repo"],
            "issue_number": number,
            "url": rec["html_url"],
            "title": rec["title"][:300],
            "created_at": created,
            "year": year,
            "state": rec["state"],
            "state_reason": rec["state_reason"],
            "comments": rec["comments"],
            "reactions": rec["reactions"],
            "labels": ";".join(rec["labels"]),
            "body_len": len(rec["body"]),
            # taxonomy
            "A_failure_type": lab.failure_type,
            "A_confidence": lab.type_confidence,
            "A_evidence": lab.evidence_span,
            "B_cause_class": lab.cause_class,
            "B_cause_secondary": lab.cause_secondary,
            "B_confidence": lab.cause_confidence,
            "B_evidence_grade": lab.cause_evidence_grade,
            "C_lifecycle_stage": lab.lifecycle_stage,
            "D_severity": lab.severity,
            "E_detection_point": lab.detection_point,
            "matched_rules": ";".join(lab.matched_rules)[:600],
            "filter_reason": reason,
            "taxonomy_version": tax.version,
        })

    records.sort(key=lambda r: (r["framework"], r["created_at"] or ""))
    write_jsonl(PROC_DIR / "failures.jsonl", records)
    write_csv(PROC_DIR / "failures.csv", records)

    # Full text kept separately so the analysis can re-derive features without
    # bloating the primary dataset, and so gold annotation can read the source.
    write_jsonl(PROC_DIR / "texts.jsonl",
                [{"record_id": k, "text": v} for k, v in text_by_id.items()])

    excl_counts = Counter(e["reason"] for e in excluded)
    write_json(PROC_DIR / "exclusions.json", {
        "generated_at": utc_now(),
        "candidates_seen": len(merged),
        "retained": len(records),
        "excluded": len(excluded),
        "exclusion_reasons": dict(excl_counts),
        "excluded_records": excluded,
    })

    # per-source audit table
    per_source = []
    for fw in sorted({r["framework"] for r in records}):
        subset = [r for r in records if r["framework"] == fw]
        per_source.append({
            "framework": fw,
            "repo": subset[0]["repo"],
            "records": len(subset),
            "with_traceback": sum(1 for r in subset
                                  if "EXC:" in r["matched_rules"] or "EXC:" in r["matched_rules"]),
            "mean_body_len": round(sum(r["body_len"] for r in subset) / len(subset), 1),
            "earliest": min((r["created_at"] or "9999") for r in subset)[:10],
            "latest": max((r["created_at"] or "") for r in subset)[:10],
        })
    write_csv(TAB_DIR / "dataset_sources.csv", per_source,
              ["framework", "repo", "records", "with_traceback", "mean_body_len",
               "earliest", "latest"])

    return records


def dedupe_stats() -> dict:
    merged = load_raw()
    return {"unique_issues": len(merged),
            "by_repo": dict(Counter(r["repo"] for r in merged.values()))}


if __name__ == "__main__":
    recs = build()
    print(f"records: {len(recs)}")
    print(Counter(r["A_failure_type"] for r in recs).most_common())
    print(Counter(r["framework"] for r in recs).most_common())

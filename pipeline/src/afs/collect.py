"""Collector for public agentic-failure records via the GitHub REST search API.

Design notes
------------
* Source of truth is the public issue tracker of agent frameworks. An issue that
  reports a defect in an agentic application is an observed failure record; this
  is the same unit used by Zhu et al. and Zhang et al. when they mine framework
  issue reports.
* Raw responses are stored verbatim (one file per query page) and never edited.
  Normalisation happens downstream so the raw corpus stays auditable.
* The exact query string, timestamp, HTTP status and remaining rate limit are
  recorded per request in `data/raw/collection_manifest.json`.
* Unauthenticated search is limited to ~10 requests/minute. The collector sleeps
  between calls and backs off on 403/429 rather than hammering the endpoint.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .common import RAW_DIR, write_json, utc_now, sha256_file

API = "https://api.github.com/search/issues"
MANIFEST_DIR = RAW_DIR / "manifests"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "afs-research-collector/1.0 (academic use)",
}

# Framework -> repository. Chosen because each is a widely used orchestration
# framework with a public, searchable issue tracker and explicit agent concepts.
SOURCES = [
    {"framework": "CrewAI", "repo": "crewAIInc/crewAI"},
    {"framework": "AutoGen", "repo": "microsoft/autogen"},
    {"framework": "LangGraph", "repo": "langchain-ai/langgraph"},
    {"framework": "MetaGPT", "repo": "geekan/MetaGPT"},
    {"framework": "OpenAI-Agents", "repo": "openai/openai-agents-python"},
    {"framework": "AutoGPT", "repo": "Significant-Gravitas/AutoGPT"},
    {"framework": "SWE-agent", "repo": "SWE-agent/SWE-agent"},
    {"framework": "LlamaIndex", "repo": "run-llama/llama_index"},
]

# Two complementary queries per repository:
#   q1 -> defects explicitly labelled as bugs by maintainers
#   q2 -> reports whose body contains a traceback, i.e. observed runtime failure
QUERIES = [
    ("label_bug", 'repo:{repo} is:issue label:bug'),
    ("traceback", 'repo:{repo} is:issue "Traceback" in:body'),
]


def _get(params: dict, attempt: int = 0) -> requests.Response:
    r = requests.get(API, params=params, headers=HEADERS, timeout=45)
    if r.status_code in (403, 429):
        # Primary or secondary rate limit: wait for the reset window.
        reset = r.headers.get("X-RateLimit-Reset")
        if reset and reset.isdigit():
            wait = max(5, int(reset) - int(time.time()) + 3)
        else:
            wait = 60
        wait = min(wait, 90)
        if attempt < 4:
            print(f"    rate limited ({r.status_code}); sleeping {wait}s", flush=True)
            time.sleep(wait)
            return _get(params, attempt + 1)
    return r


def collect(per_page: int = 100, pages: int = 3, sleep_s: float = 7.0,
            sources: list[dict] | None = None) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = MANIFEST_DIR / f"run_{run_id}.json"
    manifest = {
        "collector": "afs.collect",
        "run_id": run_id,
        "api": API,
        "started_at": utc_now(),
        "per_page": per_page,
        "pages_per_query": pages,
        "requests": [],
    }

    for src in (sources or SOURCES):
        repo = src["repo"]
        fw = src["framework"]
        for qname, qtmpl in QUERIES:
            q = qtmpl.format(repo=repo)
            for page in range(1, pages + 1):
                params = {"q": q, "per_page": per_page, "page": page,
                          "sort": "created", "order": "desc"}
                t0 = time.time()
                r = _get(params)
                entry = {
                    "framework": fw,
                    "repo": repo,
                    "query_name": qname,
                    "query": q,
                    "page": page,
                    "requested_at": utc_now(),
                    "status_code": r.status_code,
                    "elapsed_s": round(time.time() - t0, 2),
                    "rate_remaining": r.headers.get("X-RateLimit-Remaining"),
                    "rate_reset": r.headers.get("X-RateLimit-Reset"),
                }
                if r.status_code != 200:
                    entry["error"] = r.text[:400]
                    manifest["requests"].append(entry)
                    print(f"  {fw:14s} {qname:10s} p{page} -> {r.status_code}", flush=True)
                    time.sleep(sleep_s)
                    continue

                data = r.json()
                total = data.get("total_count", 0)
                items = data.get("items", [])
                entry["total_count"] = total
                entry["items_returned"] = len(items)

                # Persist the raw page verbatim.
                fname = f"{fw.lower().replace('-', '_')}__{qname}__p{page}.json"
                fpath = RAW_DIR / fname
                write_json(fpath, {
                    "query": q, "page": page, "total_count": total,
                    "fetched_at": entry["requested_at"], "items": items,
                })
                entry["raw_file"] = fname
                entry["raw_sha256"] = sha256_file(fpath)
                manifest["requests"].append(entry)
                print(f"  {fw:14s} {qname:10s} p{page} -> 200  "
                      f"total={total:5d} returned={len(items):3d}", flush=True)

                if len(items) < per_page:
                    break
                time.sleep(sleep_s)
            # gentle gap between queries as well
            time.sleep(min(sleep_s, 3))

    manifest["finished_at"] = utc_now()
    write_json(manifest_path, manifest)
    index = rebuild_index()
    ok = sum(1 for r in manifest["requests"] if r.get("status_code") == 200)
    print(f"\nrun manifest: {manifest_path}  ({ok} successful requests)")
    print(f"corpus index: {index['index_path']}  ({index['pages']} pages, "
          f"{index['unique_issues']} unique issues)")
    return manifest


def rebuild_index() -> dict:
    """Rebuild the corpus-level provenance index from the raw pages.

    The index is derived, not authoritative: it can always be regenerated from
    `data/raw/*.json`, which is why the raw pages are never edited.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pages, issues = [], set()
    for f in sorted(RAW_DIR.glob("*__*__p*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        items = payload.get("items", [])
        for it in items:
            repo = (it.get("repository_url") or "").split("/repos/")[-1]
            if repo:
                issues.add((repo, it.get("number")))
        pages.append({
            "file": f.name,
            "query": payload.get("query"),
            "page": payload.get("page"),
            "total_count": payload.get("total_count"),
            "fetched_at": payload.get("fetched_at"),
            "items": len(items),
            "sha256": sha256_file(f),
        })
    index = {
        "generated_at": utc_now(),
        "pages": len(pages),
        "unique_issues": len(issues),
        "note": ("Derived from the raw pages themselves. Per-request rate-limit "
                 "metadata lives in data/raw/manifests/run_*.json."),
        "entries": pages,
    }
    path = RAW_DIR / "collection_index.json"
    write_json(path, index)
    index["index_path"] = str(path)
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect GitHub failure records")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--sleep", type=float, default=7.0)
    args = ap.parse_args()
    collect(per_page=args.per_page, pages=args.pages, sleep_s=args.sleep)


if __name__ == "__main__":
    main()

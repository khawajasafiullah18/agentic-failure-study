"""AIDev: an independent corpus of agent-authored pull requests.

This is the second data source, and it exists to answer a different question from
the main corpus. The main corpus is built from issue reports filed in framework
trackers: every record is a failure someone chose to write down, which makes it
good for taxonomy but useless for estimating how often agents fail. AIDev is the
complement. It is a census of pull requests authored by coding agents in real
repositories, so most of its rows are not failures and no one selected them for
being interesting.

What is measured here is therefore coarse and outcome-level: did the pull request
merge, was it closed without merging, and did a human reviewer reject it. The
taxonomy is deliberately not applied. A review comment is not a failure report,
and forcing it into dimension A would produce labels that look like the main
corpus while meaning something else.

Construct limits, stated once so the numbers are not over-read:

* ``closed_unmerged`` is not the same as defective. A pull request can be closed
  because it was superseded, duplicated, or abandoned by the maintainer. It is an
  upper bound on failure, not an estimate of it.
* ``changes_requested`` is a reviewer action, not a verdict. Style complaints and
  scope disagreements are counted alongside real defects.
* AIDev-pop covers repositories with more than 100 stars, so the population is
  skewed towards projects that attract review attention in the first place.
* These are agents (Codex, Copilot, Claude Code, Cursor, Devin, Jules), not the
  frameworks the main corpus covers. The two tables answer different questions and
  must not be read as one ranking.

Source: hao-li/AIDev, tables ``pull_request`` and ``pr_reviews`` (AIDev-pop).
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import stats
from .common import TAB_DIR, read_json, utc_now, write_csv, write_json

REPO = "hao-li/AIDev"
TABLES = ("pull_request.parquet", "pr_reviews.parquet")
CACHE = TAB_DIR / "aidev_validation.json"

CONSTRUCT_NOTE = (
    "Outcome-level only. AIDev records pull requests authored by coding agents in "
    "real repositories, so the rows were not selected for being failures. Closed-"
    "unmerged is an upper bound on failure, not an estimate: a pull request can be "
    "closed because it was superseded. Changes-requested counts style and scope "
    "disagreements with real defects. The taxonomy is not applied to these rows, "
    "because a review comment is not a failure report."
)


def _paths(fetch: bool) -> list[str]:
    """Local parquet paths, downloading through the Hub cache when needed."""
    from pathlib import Path

    from huggingface_hub import hf_hub_download

    out = []
    for name in TABLES:
        if fetch:
            out.append(hf_hub_download(REPO, name, repo_type="dataset"))
        else:
            from huggingface_hub import try_to_load_from_cache

            p = try_to_load_from_cache(REPO, name, repo_type="dataset")
            if not isinstance(p, str) or not Path(p).exists():
                raise FileNotFoundError(
                    f"{name} is not in the Hub cache; run `python -m afs.cli aidev "
                    "--fetch` once to download it")
            out.append(p)
    return out


def build(fetch: bool = False) -> dict:
    """Compute per-agent outcomes. Deterministic given the same AIDev release."""
    import pandas as pd

    pr_path, rv_path = _paths(fetch)

    pr = pd.read_parquet(pr_path, columns=[
        "id", "agent", "state", "merged_at", "repo_url", "created_at", "html_url"])
    rv = pd.read_parquet(rv_path, columns=["pr_id", "state", "user_type"])

    pr["merged"] = pr["merged_at"].notna()
    pr["closed"] = pr["state"].eq("closed")

    changed = rv["state"].astype("string").str.upper().eq("CHANGES_REQUESTED")
    human = rv["user_type"].astype("string").eq("User")

    flagged_any = set(rv.loc[changed, "pr_id"].tolist())
    flagged_human = set(rv.loc[changed & human, "pr_id"].tolist())

    pr["flagged_any"] = pr["id"].isin(flagged_any)
    pr["flagged_human"] = pr["id"].isin(flagged_human)

    rows: list[dict] = []
    for agent, g in pr.groupby("agent"):
        n = int(len(g))
        merged = int(g["merged"].sum())
        closed = int(g["closed"].sum())
        closed_unmerged = int((g["closed"] & ~g["merged"]).sum())
        fh = g[g["flagged_human"]]
        lo, hi = stats.wilson_ci(merged, n)
        rows.append({
            "agent": agent,
            "pull_requests": n,
            "repositories": int(g["repo_url"].nunique()),
            "merged": merged,
            "merge_rate": round(merged / n, 4),
            "merge_rate_ci_low": round(lo, 4),
            "merge_rate_ci_high": round(hi, 4),
            "closed": closed,
            "closed_unmerged": closed_unmerged,
            "closed_unmerged_rate_of_closed": (round(closed_unmerged / closed, 4)
                                               if closed else 0.0),
            "review_flagged_human": int(len(fh)),
            "review_flagged_human_share": round(len(fh) / n, 4),
            "fixed_after_review": int(fh["merged"].sum()),
            "abandoned_after_review": int((~fh["merged"]).sum()),
        })

    rows.sort(key=lambda r: -r["pull_requests"])
    write_csv(TAB_DIR / "aidev_agent_outcomes.csv", rows,
              columns=list(rows[0].keys()))

    tot_n = int(len(pr))
    tot_merged = int(pr["merged"].sum())
    flagged_pr = pr[pr["flagged_human"]]
    summary = {
        "source": REPO,
        "tables": list(TABLES),
        "subset": "AIDev-pop (repositories with more than 100 stars)",
        "pull_requests": tot_n,
        "repositories": int(pr["repo_url"].nunique()),
        "agents": int(pr["agent"].nunique()),
        "merged": tot_merged,
        "merge_rate": round(tot_merged / tot_n, 4),
        "closed_unmerged": int((pr["closed"] & ~pr["merged"]).sum()),
        "review_flagged_human": int(len(flagged_pr)),
        "fixed_after_review": int(flagged_pr["merged"].sum()),
        "abandoned_after_review": int((~flagged_pr["merged"]).sum()),
        "repair_rate_after_review": (round(float(flagged_pr["merged"].mean()), 4)
                                     if len(flagged_pr) else None),
        "construct_note": CONSTRUCT_NOTE,
        "generated_at": utc_now(),
    }
    payload = {"summary": summary, "per_agent": rows}
    write_json(TAB_DIR / "aidev_validation.json", payload)
    return payload


def load() -> dict:
    """Cached payload, or an empty shell so the report renders without the tables."""
    try:
        return read_json(TAB_DIR / "aidev_validation.json")
    except Exception:
        return {}


def _main(argv: list[str]) -> int:
    out = build(fetch="--fetch" in argv)
    s = out["summary"]
    print(json.dumps(s, indent=2))
    print(f"\n{len(out['per_agent'])} agents -> outputs/tables/aidev_agent_outcomes.csv")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))

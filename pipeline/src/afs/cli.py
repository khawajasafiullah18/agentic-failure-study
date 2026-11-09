"""Command line entry point.

    python -m afs.cli collect     # fetch public failure records
    python -m afs.cli build       # normalise + label -> dataset
    python -m afs.cli analyze     # run the multi-agent analysis pipeline
    python -m afs.cli validate    # run validation experiments
    python -m afs.cli export      # render the Word deliverable
    python -m afs.cli hf          # build the Hugging Face dataset package
    python -m afs.cli all         # build -> analyze -> validate -> export -> hf
"""
from __future__ import annotations

import argparse
import json
import sys

from .common import AuditLog, OUT_DIR, PROC_DIR, TAB_DIR, read_jsonl, utc_now, write_json


def _texts() -> dict[str, str]:
    return {r["record_id"]: r["text"] for r in read_jsonl(PROC_DIR / "texts.jsonl")}


def cmd_collect(args) -> None:
    from .collect import collect

    collect(pages=args.pages, sleep_s=args.sleep)


def cmd_build(args) -> None:
    from . import dataset

    recs = dataset.build()
    print(f"records built: {len(recs)}")
    from collections import Counter

    print("failure types:", Counter(r["A_failure_type"] for r in recs).most_common())
    print("frameworks:", Counter(r["framework"] for r in recs).most_common())


def cmd_analyze(args) -> None:
    from .agents import Orchestrator, load_rq_config
    from .analysis import export_tables, load_records

    records = load_records()
    print(f"loaded {len(records)} records")
    orch = Orchestrator(records, load_rq_config())
    summary = orch.run()
    export_tables(orch.bb.results)
    print(json.dumps(summary, indent=2))


def cmd_validate(args) -> None:
    from . import exemplars, findings_validation, validation
    from .analysis import load_records
    from .complexity import measure_quality

    records = load_records()
    texts = _texts()
    out = validation.run_all(records, texts)
    print(json.dumps({k: v for k, v in out.items()
                      if k in ("gold_status", "gold_sample_size")}, indent=2))
    print("perturbation retention:", out["perturbation"]["retention_rate"])
    print("ablation change rate:", out["ablation"]["change_rate"])

    fv = findings_validation.run_all(records)
    print("findings validation:", json.dumps(fv["summary"], indent=2))

    cx = measure_quality(records, texts)
    print("complexity tiers:", [(t["tier"], t["records"]) for t in cx["distribution"]])

    ex = exemplars.build(records, texts)
    print("exemplars:", ex["exemplars"], "across", ex["categories"], "categories")


def cmd_requirements(args) -> None:
    from . import requirements

    print(json.dumps(requirements.export(), indent=2))


def cmd_export(args) -> None:
    from .docx_export import export_all

    path = export_all()
    print(f"deliverable written: {path}")


def cmd_handover(args) -> None:
    from .handover import build_all

    for k, v in build_all().items():
        print(f"{k}: {v}")


def cmd_paper(args) -> None:
    from .paper import export_paper

    print(f"manuscript written: {export_paper()}")


def cmd_app(args) -> None:
    from .webapp import build_app

    path = build_app()
    print(f"application written: {path}")
    print("open it by double-clicking index.html (no server or install needed)")


def cmd_bundle(args) -> None:
    from .server import bundle

    print(f"analysis bundle written: {bundle()}")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("afs.server:app", host=args.host, port=args.port,
                log_level="info", proxy_headers=True,
                forwarded_allow_ips="127.0.0.1")


def cmd_score_coder(args) -> None:
    from .validation import kappa_from_sheet

    out = kappa_from_sheet()
    print(json.dumps(out, indent=2))
    if out.get("status") != "complete":
        print("fill data/gold/second_coder_sheet.csv (coder2_label) first")


def cmd_hf(args) -> None:
    from .hf_export import build

    m = build()
    print(f"hugging face package: {m['records']} records, "
          f"{m['columns']} columns, {m['exemplars']} exemplars")
    print("files:", ", ".join(m["files"]))
    print("publish with: python deploy/push_hf.py --repo-id <user>/<name> --yes")


def cmd_aidev(args) -> None:
    from . import aidev

    out = aidev.build(fetch=getattr(args, "fetch", False))
    s = out["summary"]
    print(f"AIDev: {s['pull_requests']:,} agent-authored PRs across "
          f"{s['repositories']:,} repositories, {s['agents']} agents; "
          f"merge rate {s['merge_rate']:.1%}")


def cmd_all(args) -> None:
    from .common import RunRecord

    audit = AuditLog()
    rec = RunRecord(step="pipeline_all")
    cmd_build(args)
    cmd_analyze(args)
    cmd_validate(args)
    cmd_export(args)
    cmd_paper(args)
    cmd_app(args)
    cmd_requirements(args)
    cmd_hf(args)
    audit.append(rec.finish("ok"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="afs", description="Agentic failure study")
    ap.add_argument("command", choices=["collect", "build", "analyze", "validate",
                                        "export", "paper", "app", "bundle",
                                        "serve", "handover", "score-coder",
                                        "requirements", "hf", "aidev", "all"])
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=7.0)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8097)
    ap.add_argument("--fetch", action="store_true",
                    help="download the AIDev tables through the Hub cache")
    args = ap.parse_args(argv)

    {"collect": cmd_collect, "build": cmd_build, "analyze": cmd_analyze,
     "validate": cmd_validate, "export": cmd_export, "paper": cmd_paper,
     "app": cmd_app, "bundle": cmd_bundle, "serve": cmd_serve,
     "handover": cmd_handover, "score-coder": cmd_score_coder,
     "requirements": cmd_requirements, "hf": cmd_hf, "aidev": cmd_aidev,
     "all": cmd_all}[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Analysis service

Runtime bundle for agentic.theaiplusplus.com. Built by
`deploy/build_service.py`; do not edit by hand.

`src/afs/server.py` exposes the multi-agent engine over HTTP. `data/processed/records_enriched.jsonl` is the analysis-ready corpus (the raw issue text is not shipped).

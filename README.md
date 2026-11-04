# Failures in Agentic AI — analysis application

**Live: https://agentic.theaiplusplus.com/**

A working application over a study of **3,089 publicly reported failures** across
eight agent orchestration frameworks.

The root URL is not a report. It is an analysis console. You ask a question in
plain language; the multi-agent engine routes it to the research questions it
matches, computes each with the study's statistical code, and a critic
recomputes every headline number from the raw records before the answer is
displayed. The agent trace is shown live, step by step.

- **Ask** — put a question to the engine; watch the planner, tagger, specialists
  and critic work; download the result table as CSV
- **Classify** — paste a traceback or error report and get the five taxonomy
  dimensions, the evidence span that decided the label, and a three-part action
  plan (do now, then, guardrail) plus the closest cases already in the corpus
- **Corpus** — server-side search and filtering over all 3,089 records, with the
  evidence span and a link to each original report
- **Questions** — the ten research questions, their owning agent and method, each
  runnable with one click
- **How it works** — what the agent chain does with an answer, and what it refuses
  to claim

The written report, figures, codebook and downloads remain at
**https://agentic.theaiplusplus.com/report/**.

## Layout

```
index.html                     the report (self-contained, served at /report/)
data/                          report data files (CSV / JSONL)
service/src/afs/server.py      the HTTP surface over the agent engine
service/src/afs/agents.py      planner, tagger, specialists, critic, reporter
service/src/afs/analysis.py    the statistics behind every answered question
service/data/processed/        analysis-ready records (raw issue text is not shipped)
```

## Deployment

`.github/workflows/deploy.yml` runs on every push to `main`:

1. **guard** refuses credential-shaped strings in deployed files, verifies the
   embedded record count, parses every service module, and checks the analysis
   corpus is complete;
2. **report** rsyncs the static report to the document root over a key confined
   to that directory by `rrsync`;
3. **service** tars `service/` and streams it over a second key whose only
   capability is a forced-command script: it unpacks into a timestamped release,
   restarts `agentic-api.service`, health-checks `/api/health`, and rolls back to
   the previous release if the check fails;
4. **verify** probes HTTPS, asks the engine a real question, asserts the answer
   is verified and non-empty, and checks the report still renders.

Neither key can open a shell or write outside its own target, so the other sites
on the host are not reachable from this pipeline.

## Rebuilding

```bash
python -m afs.cli app      # regenerate the report at outputs/app/index.html
python -m afs.cli bundle   # regenerate the analysis-ready records
python deploy/build_service.py   # assemble the deployable service bundle
python -m afs.cli serve --port 8097   # run the console locally
```

## What the engine will not do

It answers with counts, intervals and association strength, never with a causal
claim that the data cannot support. If a question matches no research question,
the response says so and labels the fallback rather than inventing an answer.
The corpus is issue-tracker data: it records what people chose to report, so
shares describe that population, not all failures in production.

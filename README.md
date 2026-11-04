# Failures in Agentic AI — study explorer

A browser application for a study of **3,089 publicly reported failures** across
eight agent orchestration frameworks.

- **Overview** — the four headline findings, with intervals
- **Explore records** — search and filter the whole corpus; open any record to
  see its evidence span, the rules that produced its label, and a link to the
  original report
- **Frameworks** — composition, blocking rate and silent-failure rate per framework
- **Taxonomy** — the five-dimension codebook, with definitions and inclusion /
  exclusion lists
- **Research questions** — each question, the method used, and the finding
- **Validation** — the five experiments that test the labelling instrument
- **Data & downloads** — the corpus, codebook and result tables

Everything is embedded in one HTML file, so the page works offline and needs no
server. Rebuild it with:

```bash
python -m afs.cli app
```

The corpus is issue-tracker data. It describes what people chose to report, not
the population of all failures; frequency shares should be read accordingly.

# Analysis pipeline

This folder is the code that produced every number, table and figure in the study report.
The application in the parent folder shows the results; this folder is how they were made.

The command-line equivalent of "Run all" is:

```
pip install -r requirements.lock.txt
set PYTHONPATH=src

python -m afs.cli analyze      # ten RQ tables + analysis_results.json
python -m afs.cli validate     # instrument suite E1-E5, findings suite F1-F4
python -m afs.cli requirements # 26-row traceability matrix
python -m afs.cli export       # report, paper, deck, one-pager, coder packet
python -m afs.cli score-coder  # Cohen's kappa once the 40-row sheet is filled
```

`analyze` and `validate` need the labelled corpus in `data/processed/`, which is the same
data exposed by the application. `python -m pytest tests` checks the pipeline end to end.

`EVIDENCE_MAP.md` maps each research question to the function, output table and figure that
produces it.

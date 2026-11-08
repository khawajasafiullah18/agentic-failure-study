"""Shared utilities: provenance, atomic IO, hashing, logging.

Every artifact written by this project is accompanied by a SHA-256 digest and
an entry in the run manifest so that any reported number can be traced back to
the exact bytes that produced it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROC_DIR = DATA_DIR / "processed"
GOLD_DIR = DATA_DIR / "gold"
OUT_DIR = ROOT / "outputs"
FIG_DIR = OUT_DIR / "figures"
TAB_DIR = OUT_DIR / "tables"
REP_DIR = OUT_DIR / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_count() -> int:
    """Number of test methods in ``tests/``.

    Prose in the report, paper and deck quotes this figure, so it is counted
    from the source rather than hard-coded: adding a test can never make a
    printed claim stale. Returns 0 when the tests directory is absent (for
    example in an installed package).
    """
    root = ROOT / "tests"
    if not root.is_dir():
        return 0
    n = 0
    for f in sorted(root.glob("test_*.py")):
        try:
            n += f.read_text(encoding="utf-8").count("\n    def test_")
        except OSError:
            continue
    return n


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROC_DIR, GOLD_DIR, FIG_DIR, TAB_DIR, REP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = columns or list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in cols})


def read_csv(path: Path) -> list[dict]:
    import csv

    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@dataclass
class RunRecord:
    """One step of the pipeline, recorded for auditability."""

    step: str
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    status: str = "running"
    details: dict = field(default_factory=dict)

    def finish(self, status: str = "ok", **details) -> "RunRecord":
        self.finished_at = utc_now()
        self.status = status
        self.details.update(details)
        return self


class AuditLog:
    """Append-only JSONL log of pipeline steps.

    Each entry carries the python/platform context so that a reviewer can tell
    which environment produced a given number.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (OUT_DIR / "run_audit.jsonl")

    def append(self, rec: RunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(rec)
        payload["env"] = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": os.getcwd(),
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def stable_id(*parts: str) -> str:
    """Deterministic short id, used where a record needs a reproducible key."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return h[:16]


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def elapsed(t0: float) -> float:
    return round(time.perf_counter() - t0, 3)

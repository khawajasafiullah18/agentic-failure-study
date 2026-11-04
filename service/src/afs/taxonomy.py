"""Taxonomy loading, validation and codebook rendering.

The YAML file in `configs/` is the single source of truth for category
definitions. Code validates it on load so that a malformed codebook fails loudly
instead of silently producing unlabelled data.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .common import CONFIG_DIR, TAB_DIR, write_json, write_csv

TAXONOMY_PATH = CONFIG_DIR / "taxonomy.v1.yaml"

DIMENSIONS = ["A_failure_type", "B_cause_class", "C_lifecycle_stage",
              "D_severity", "E_detection_point"]


class Taxonomy:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or TAXONOMY_PATH
        with open(self.path, "r", encoding="utf-8") as fh:
            self.spec = yaml.safe_load(fh)
        self.validate()

    # ------------------------------------------------------------------ checks
    def validate(self) -> None:
        for dim in DIMENSIONS:
            if dim not in self.spec["dimensions"]:
                raise ValueError(f"taxonomy missing dimension {dim}")
            cats = self.spec["dimensions"][dim]["categories"]
            if len(cats) < 2:
                raise ValueError(f"dimension {dim} has fewer than two categories")
            for key, body in cats.items():
                if isinstance(body, dict) and "definition" not in body:
                    raise ValueError(f"{dim}/{key} has no definition")
                if isinstance(body, dict) and not body.get("label"):
                    raise ValueError(f"{dim}/{key} has no label")
        # dimension A must be single-label for the study's primary statistic
        if self.spec["dimensions"]["A_failure_type"].get("multi_label"):
            raise ValueError("dimension A must be single-label")

    # ------------------------------------------------------------------ access
    @property
    def version(self) -> str:
        return str(self.spec["meta"]["version"])

    def categories(self, dim: str) -> dict[str, dict | str]:
        return self.spec["dimensions"][dim]["categories"]

    def codes(self, dim: str) -> list[str]:
        return list(self.categories(dim).keys())

    def label(self, dim: str, code: str) -> str:
        body = self.categories(dim).get(code)
        if isinstance(body, dict):
            return body.get("label", code)
        return body or code

    def definition(self, dim: str, code: str) -> str:
        body = self.categories(dim).get(code)
        if isinstance(body, dict):
            return body.get("definition", "")
        return str(body or "")

    def patterns(self) -> list[tuple[str, str, str]]:
        """(dimension, code, pattern) triples drawn from the codebook examples."""
        out = []
        for code, body in self.categories("A_failure_type").items():
            if isinstance(body, dict):
                for pat in body.get("example_patterns", []):
                    out.append(("A_failure_type", code, str(pat).lower()))
        for code, body in self.categories("B_cause_class").items():
            if isinstance(body, dict):
                for pat in body.get("signals", []):
                    out.append(("B_cause_class", code, str(pat).lower()))
        return out

    # ------------------------------------------------------------------ export
    def to_markdown(self) -> str:
        m = self.spec["meta"]
        lines = [
            "# Failure Taxonomy v%s" % m["version"],
            "",
            "**Frozen:** %s  " % m["frozen"],
            "**Unit of analysis:** %s" % m["unit_of_analysis"],
            "",
            "> " + " ".join(str(m["coding_unit_note"]).split()),
            "",
            "## Dimensions",
            "",
            "| Dimension | Coding | Categories |",
            "|---|---|---|",
        ]
        for dim in DIMENSIONS:
            body = self.spec["dimensions"][dim]
            multi = "multi-label" if body.get("multi_label") else "single-label"
            lines.append(f"| {dim} | {multi} | {len(body['categories'])} |")
        lines.append("")

        for dim in DIMENSIONS:
            body = self.spec["dimensions"][dim]
            lines.append(f"## {dim}")
            lines.append("")
            if body.get("description"):
                lines.append(" ".join(str(body["description"]).split()))
                lines.append("")
            for code, cat in body["categories"].items():
                if isinstance(cat, str):
                    lines.append(f"- **{code}** — {cat}")
                    continue
                lines.append(f"### {code}: {cat.get('label', code)}")
                lines.append("")
                if cat.get("definition"):
                    lines.append(" ".join(str(cat["definition"]).split()))
                    lines.append("")
                if cat.get("include"):
                    lines.append("**Codes here when:**")
                    for inc in cat["include"]:
                        lines.append(f"- {inc}")
                    lines.append("")
                if cat.get("exclude"):
                    lines.append("**Not this category when:**")
                    for exc in cat["exclude"]:
                        lines.append(f"- {exc}")
                    lines.append("")
                if cat.get("example_patterns") or cat.get("signals"):
                    pats = cat.get("example_patterns") or cat.get("signals")
                    lines.append("**Lexical signals used by the automated labeller:** "
                                 + ", ".join(f"`{p}`" for p in pats))
                    lines.append("")
            lines.append("")

        rules = self.spec.get("coding_rules", [])
        if rules:
            lines.append("## Coding rules")
            lines.append("")
            for r in rules:
                lines.append(f"**{r['rule']}** — " + " ".join(str(r["detail"]).split()))
                lines.append("")
        return "\n".join(lines)

    def export_tables(self) -> None:
        rows = []
        for dim in DIMENSIONS:
            for code, cat in self.categories(dim).items():
                if isinstance(cat, str):
                    rows.append({"dimension": dim, "code": code, "label": code,
                                 "definition": cat, "include": "", "exclude": ""})
                else:
                    rows.append({
                        "dimension": dim,
                        "code": code,
                        "label": cat.get("label", code),
                        "definition": " ".join(str(cat.get("definition", "")).split()),
                        "include": " | ".join(cat.get("include", [])),
                        "exclude": " | ".join(cat.get("exclude", [])),
                    })
        write_csv(TAB_DIR / "taxonomy_categories.csv", rows,
                  ["dimension", "code", "label", "definition", "include", "exclude"])
        write_json(TAB_DIR / "taxonomy_spec.json", self.spec)

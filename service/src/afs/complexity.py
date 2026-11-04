"""Operationalise 'agent complexity' from what a report says about the
architecture that failed.

This is deliberately a *declared* complexity measure, not ground truth: it
counts the architectural capabilities the reporter mentions. The limitation is
stated in the report, because a textual proxy can under-count capabilities that
were present but not described.
"""
from __future__ import annotations

import re

from .stats import proportion_row

ROLE_TERMS = [
    r"planner", r"developer", r"coder", r"tester", r"reviewer", r"critic",
    r"researcher", r"writer", r"manager", r"supervisor", r"worker",
    r"executor", r"architect", r"analyst", r"specialist", r"coordinator",
]
MULTI_AGENT_TERMS = [
    r"\bcrew\b", r"\bteam\b", r"multi-?agent", r"\bgroup ?chat\b",
    r"\bhandoff\b", r"\bdelegat", r"\borchestrat", r"\bagents\b",
    r"\bcollaborat", r"\bswarm\b", r"round ?robin", r"\bgraph\b",
]
TOOL_TERMS = [
    r"\btools?\b", r"function call", r"\bmcp\b", r"\bplugin", r"\bconnector",
    r"\bapi\b", r"\bbrowser\b", r"\bsearch\b", r"\bretriev", r"\bvector",
    r"\brag\b", r"\bscrap", r"\bsql\b", r"\bcode execution\b", r"\bsandbox\b",
]
MEMORY_TERMS = [
    r"\bmemor(y|ies)\b", r"\bcheckpoint", r"\bpersist", r"\bstate\b",
    r"\bconversation history\b", r"\bcontext window\b", r"\bvector store\b",
]


def _hits(text: str, terms: list[str]) -> tuple[int, list[str]]:
    found = []
    for t in terms:
        rx = re.compile(t, re.I)
        m = rx.search(text)
        if m:
            found.append(m.group(0).lower())
    return len(found), sorted(set(found))


def complexity_features(text: str) -> dict:
    role_n, role_terms = _hits(text, ROLE_TERMS)
    multi_n, multi_terms = _hits(text, MULTI_AGENT_TERMS)
    tool_n, tool_terms = _hits(text, TOOL_TERMS)
    mem_n, mem_terms = _hits(text, MEMORY_TERMS)

    multi_agent = multi_n >= 2 or role_n >= 3
    uses_tools = tool_n >= 1
    uses_memory = mem_n >= 1
    tier = int(multi_agent) + int(uses_tools) + int(uses_memory)

    return {
        "roles_mentioned": role_n,
        "multi_agent_evidence": multi_n,
        "tool_evidence": tool_n,
        "memory_evidence": mem_n,
        "multi_agent": multi_agent,
        "uses_tools": uses_tools,
        "uses_memory": uses_memory,
        "complexity_tier": tier,
        "complexity_label": ["0_capabilities", "1_capability",
                             "2_capabilities", "3_capabilities"][tier],
        "capability_terms": ",".join(role_terms + multi_terms + tool_terms + mem_terms)[:300],
    }


def enrich(records: list[dict], full_text: dict[str, str] | None = None) -> list[dict]:
    """Attach complexity features to each record.

    `full_text` maps record_id -> issue text. When absent, the stored title and
    evidence span are used, which under-counts capabilities and therefore biases
    the complexity analysis conservatively.
    """
    out = []
    for r in records:
        parts = [str(r.get("title", "")), str(r.get("A_evidence", ""))]
        if full_text:
            parts.append(str(full_text.get(r["record_id"], "")))
        feats = complexity_features(" ".join(parts))
        out.append({**r, **feats})
    return out


def tier_summary(records: list[dict]) -> list[dict]:
    rows = []
    for tier in range(4):
        sub = [r for r in records if r.get("complexity_tier") == tier]
        if not sub:
            continue
        orch = sum(1 for r in sub if r["A_failure_type"] in
                   ("A4_communication", "A5_context_memory"))
        row = proportion_row(orch, len(sub), f"tier_{tier}")
        row.update({"tier": tier, "records": len(sub),
                    "orchestration_or_context_failures": orch})
        rows.append(row)
    return rows

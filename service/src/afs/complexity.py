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


# --------------------------------------------------------------------------- #
# Formal definition and measurement quality
# --------------------------------------------------------------------------- #
DEFINITION = {
    "construct": "declared architectural complexity of the failing system",
    "status": ("a declared, text-derived proxy. It is NOT instrumented, NOT a "
               "count of executed agents, and NOT a ground-truth architecture "
               "measurement. Every claim about it is conditional on that."),
    "operationalisation": (
        "Three binary capabilities are read from the issue text with fixed "
        "lexicons. Each counts 1 when the record contains at least one term for "
        "that capability; the index is their sum, giving an ordinal scale 0-3."),
    "components": [
        {"name": "multi_agent",
         "rule": ">=2 distinct multi-agent terms, or >=3 distinct agent-role terms",
         "rationale": ("A single role name can appear in a single-agent project; "
                       "two orchestration terms or three distinct roles indicate "
                       "an actual division of labour.")},
        {"name": "uses_tools",
         "rule": ">=1 tool/integration term (tool, function call, MCP, plugin, "
                 "retrieval, RAG, sandbox, ...)",
         "rationale": "A tool interface is a failure surface that does not exist in a text-only pipeline."},
        {"name": "uses_memory",
         "rule": ">=1 state/memory term (memory, checkpoint, persist, state, "
                 "conversation history, vector store)",
         "rationale": "Retained state is what makes context corruption observable."},
    ],
    "scale": {
        "0": "no capability declared beyond a single prompt",
        "1": "one capability",
        "2": "two capabilities",
        "3": "all three capabilities",
    },
    "known_limitations": [
        "Under-counts capabilities that were present but not described in the report.",
        "A long, detailed report has more chances to match a lexicon term, so the "
        "index can correlate with report verbosity; this is measured and reported.",
        "The lexicons are fixed in source and were not tuned on the outcome, which "
        "prevents the index from being fitted to the result it is used to explain.",
    ],
}


def definition() -> dict:
    return DEFINITION


def measure_quality(records: list[dict], texts: dict[str, str] | None = None) -> dict:
    """Report the properties a reader needs to judge the complexity measure.

    Four checks, each aimed at a specific way the analysis could be wrong:

    * distribution     - is every tier populated enough to compare?
    * text dependence   - does the tier change when only the title and evidence
                          span are used instead of the full issue text? A large
                          change means the measure is sensitive to how much text
                          a reporter supplied.
    * component check   - does each capability separately track the outcome, or
                          does the result rest on one component only?
    * verbosity control - is the index just a proxy for issue length?
    """
    from .common import TAB_DIR, write_json, utc_now

    out: dict = {"definition": DEFINITION, "n": len(records), "generated_at": utc_now()}

    # distribution
    tiers = []
    for tier in range(4):
        sub = [r for r in records if r.get("complexity_tier") == tier]
        tiers.append({"tier": tier, "records": len(sub),
                      "share": round(len(sub) / max(len(records), 1), 4)})
    out["distribution"] = tiers

    # text dependence: conservative input vs full text
    if texts:
        same, n = 0, 0
        deltas = []
        for r in records:
            conservative = complexity_features(
                f"{r.get('title', '')} {r.get('A_evidence', '')}")
            n += 1
            d = int(r.get("complexity_tier", 0)) - conservative["complexity_tier"]
            deltas.append(d)
            if d == 0:
                same += 1
        out["text_dependence"] = {
            "same_tier_share": round(same / max(n, 1), 4),
            "mean_tier_shift_from_full_text": round(sum(deltas) / max(n, 1), 3),
            "note": ("Share of records whose tier is unchanged when only the "
                     "title and evidence span are read. A low share means the "
                     "measure needs the full report and is therefore sensitive "
                     "to reporting completeness."),
        }

    # component check: each capability on/off vs orchestration/context outcome
    orch_types = ("A4_communication", "A5_context_memory")
    comp = {}
    for name in ("multi_agent", "uses_tools", "uses_memory"):
        on = [r for r in records if r.get(name)]
        off = [r for r in records if not r.get(name)]
        def rate(sub):
            return round(sum(1 for r in sub if r["A_failure_type"] in orch_types)
                         / max(len(sub), 1), 4)
        comp[name] = {"with": rate(on), "without": rate(off),
                      "n_with": len(on), "n_without": len(off),
                      "difference_pp": round((rate(on) - rate(off)) * 100, 2)}
    out["component_check"] = comp

    # verbosity control
    from .stats import spearman_trend
    tiers_x = [r.get("complexity_tier", 0) for r in records]
    lens = [max(len(str(r.get("title", ""))) + int(r.get("body_len") or 0), 1)
            for r in records]
    tr = spearman_trend(tiers_x, lens)
    out["verbosity_control"] = {
        "rho_tier_vs_report_length": tr.get("rho"),
        "p_value": tr.get("p_value"),
        "note": ("If rho were near 1 the index would be a length proxy. A moderate "
                 "positive rho is expected (complex systems get longer reports) but "
                 "must not be mistaken for the mechanism."),
    }

    write_json(TAB_DIR / "complexity_definition.json", out)
    return out

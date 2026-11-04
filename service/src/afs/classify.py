"""Deterministic, auditable failure labeller.

Design position
---------------
The labeller is rule-based rather than LLM-based on purpose:

* the taxonomy study needs labels that a reviewer can reproduce byte for byte;
* every label carries the matched evidence span, so a disagreement can be
  adjudicated against the text rather than against a model;
* it runs offline, so the pipeline is runnable by anyone marking the work.

An optional LLM adjudicator can be plugged in for low-confidence records
(`LLMAdjudicator`), but it never overwrites a confident deterministic label and
its suggestions are recorded separately in the output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .taxonomy import Taxonomy

# --------------------------------------------------------------------------- #
# Lexicons. Weights: 3.0 decisive, 2.0 strong, 1.0 supporting, <1 weak.
# --------------------------------------------------------------------------- #
A_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "A1_functionality": [
        (r"\bincorrect(ly)?\b", 1.6), (r"\bwrong\b", 1.4),
        (r"\binaccurate\b", 1.4), (r"hallucinat", 2.0),
        (r"does not (work|follow|respect)", 1.6),
        (r"fail(s|ed)? to (follow|respect|produce|return)", 1.2),
        (r"ignor(e|es|ed) (the )?(instruction|prompt|requirement)", 1.6),
        (r"unexpected(ly)? (result|output|behaviou?r)", 1.2),
        (r"\bnot working\b", 1.0), (r"\bbroken\b", 0.8),
        (r"returns? .{0,20}(wrong|incorrect|empty)", 1.2),
        (r"silently (skip|drop|fail)", 1.8),
        (r"\bnameerror\b", 2.2), (r"\bruntimeerror\b", 1.4),
        (r"\bassertionerror\b", 1.4), (r"stops? with (an )?error", 1.4),
        (r"crashes? (after|when|with)", 1.4),
        (r"error when", 1.0), (r"not handled", 1.2),
        (r"unexpected error", 1.2),
    ],
    "A2_tool_integration": [
        (r"\btool[_ ]?calls?\b", 2.6), (r"\btool_calls\b", 2.6),
        (r"\b(tool|function)[_ ]?(use|usage|call|invocation|selection)\b", 2.0),
        (r"\bmcp\b", 2.6), (r"@tool\b", 2.2),
        (r"toolexception", 2.8), (r"tool not found", 2.8),
        (r"unknown tool", 2.2), (r"structured tool", 1.6),
        (r"tool_choice", 1.6), (r"function calling", 2.0),
        (r"tool (registry|schema|description)", 1.8),
        (r"(tools?|mcp).{0,30}(not (available|registered|exposed))", 2.2),
    ],
    "A3_compatibility": [
        (r"unexpected keyword argument", 3.0),
        (r"got an unexpected keyword", 3.0),
        (r"cannot import name", 3.0), (r"no module named", 2.4),
        (r"modulenotfounderror", 2.4), (r"\bimporterror\b", 2.0),
        (r"incompatib", 2.2), (r"breaking change", 2.6),
        (r"deprecat", 1.6), (r"requires? (python|version)", 1.6),
        (r"\btypeerror\b", 1.8), (r"\battributeerror\b", 1.4),
        (r"has no attribute", 2.0),
        (r"\bversion\b", 0.7), (r"\bupgrad(e|ed|ing)\b", 1.2),
    ],
    "A4_communication": [
        (r"\bhandoff\b", 2.6), (r"\bhand off\b", 2.0),
        (r"\bdelegat(e|ion|ing)\b", 2.0), (r"\bgroup ?chat\b", 2.6),
        (r"\bround ?robin\b", 2.6), (r"speaker selection", 3.0),
        (r"select_speaker", 3.0), (r"multi-?agent", 1.4),
        (r"\bmanager\b", 1.2), (r"\bteammate", 1.6),
        (r"max(imum)? (turns|rounds)", 2.0), (r"infinite loop", 1.6),
        (r"agent.{0,12}(→|to|->).{0,12}agent", 1.6),
        (r"(conversation|chat).{0,25}(stop|terminat|loop|stuck)", 1.6),
        (r"\bsupervisor\b", 1.0), (r"\bcrew\b", 0.9),
    ],
    "A5_context_memory": [
        (r"context window", 2.6), (r"token limit", 2.0),
        (r"truncat", 2.0), (r"conversation history", 2.0),
        (r"\bmemory\b", 1.2), (r"checkpoint", 1.6),
        (r"lost.{0,20}(context|history|state|memory)", 2.2),
        (r"(not|never) (passed|forwarded|preserved)", 1.4),
        (r"\bstate\b", 0.7), (r"prompt overflow", 2.4),
        (r"overflow", 1.4), (r"too (much|many) (context|tokens)", 2.0),
    ],
    "A6_data_structure": [
        (r"validation ?error", 3.0), (r"pydantic", 2.6),
        (r"jsondecodeerror", 3.0), (r"json (parse|decod)", 2.6),
        (r"output parser", 2.6), (r"failed to parse", 2.6),
        (r"\bschema\b", 1.5), (r"\bkeyerror\b", 1.5),
        (r"serializ", 1.5), (r"malformed", 1.6),
        (r"(output|response).{0,20}(not valid|invalid) (json|struct)", 2.4),
        (r"\bdataclass\b", 1.0),
    ],
    "A7_configuration": [
        (r"api key", 2.0), (r"environment variable", 2.2),
        (r"\benv var", 2.2), (r"not configured", 2.2),
        (r"configuration", 1.0), (r"pip install", 1.8),
        (r"\binstall", 0.8), (r"\bdocker\b", 1.2),
        (r"credentials", 1.6), (r"\bsettings\b", 1.0),
        (r"(missing|required).{0,20}(env|key|credential)", 2.0),
    ],
    "A8_performance": [
        (r"\btimeout\b", 2.6), (r"timed out", 2.6),
        (r"rate ?limit", 2.6), (r"\b429\b", 2.6),
        (r"out of memory", 2.6), (r"memoryerror", 2.6),
        (r"too (slow|long)", 1.8), (r"\bexceeded\b", 1.2),
        (r"\bdeadline\b", 1.2), (r"quota", 1.6),
    ],
    "A9_safety": [
        (r"prompt injection", 3.0), (r"\binjection\b", 1.8),
        (r"\bunsafe\b", 1.8), (r"\bsecurity\b", 1.6),
        (r"permission denied", 1.8), (r"\bsandbox\b", 1.5),
        (r"\bvulnerab", 2.2), (r"\bexploit\b", 1.8),
    ],
}

B_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "B1_framework_defect": [
        (r"bug in (the )?(framework|crewai|autogen|langgraph)", 3.0),
        (r"(maintainer|internal) (fix|confirmed|bug)", 2.0),
        (r"fixed in (v|version)", 2.2),
        (r"regression (in|introduced)", 2.0),
        (r"(internal|itself) (error|exception)", 1.6),
    ],
    "B2_api_version_drift": [
        (r"after (upgrad|updat)", 3.0), (r"since (v|version|upgrad)", 2.6),
        (r"(was|has been) renamed", 2.6), (r"removed in", 2.4),
        (r"breaking change", 2.6), (r"(newer|latest) version", 1.8),
    ],
    "B3_configuration_error": [
        (r"(forgot|missing|did not set|not set)", 1.8),
        (r"misconfigur", 2.6), (r"env(ironment)? var", 1.8),
        (r"api key", 1.6), (r"\.env\b", 1.6),
    ],
    "B4_specification_ambiguity": [
        (r"\bdocs?(umentation)?\b", 1.6),
        (r"(unclear|ambiguous|not documented|no documentation)", 2.4),
        (r"docs? (say|state|suggest)", 2.0),
        (r"expected (behaviou?r|it to)", 1.2),
    ],
    "B5_model_limitation": [
        (r"hallucinat", 2.6), (r"(small|weaker|cheaper) model", 2.0),
        (r"model (cannot|can't|fails to)", 2.2),
        (r"instruction.{0,20}follow", 1.8),
        (r"(ignores|disregards) (the )?(instruction|prompt)", 2.0),
        (r"temperature", 1.2),
    ],
    "B6_context_management": [
        (r"context (window|length|size)", 2.4),
        (r"(history|context).{0,20}(lost|not passed|missing)", 2.2),
        (r"truncat", 2.0), (r"token (limit|budget)", 1.8),
        (r"checkpoint|resume", 1.6),
    ],
    "B7_tool_environment": [
        (r"(server|service).{0,20}(unavailable|down|offline)", 2.4),
        (r"connection (refused|error|reset)", 2.2),
        (r"network (error|issue|failure)", 2.0),
        (r"(tool|mcp).{0,20}(not running|unreachable)", 2.2),
    ],
    "B8_application_logic": [
        (r"(my|our) (code|function|implementation)", 2.0),
        (r"wrong (logic|implementation|code)", 2.2),
        (r"typo", 1.8), (r"i (wrote|implemented)", 1.6),
    ],
    "B9_expectation_mismatch": [
        (r"(by design|working as (intended|designed))", 3.0),
        (r"(not|isn't) a bug", 2.6), (r"expected behaviou?r", 2.2),
    ],
}

# Exception type -> (dimension A code, weight). Structural, so high weight.
EXCEPTION_RULES: list[tuple[str, str, float]] = [
    ("unexpected keyword argument", "A3_compatibility", 1.5),
    ("cannot import name", "A3_compatibility", 1.5),
    ("no module named", "A3_compatibility", 1.0),
    ("modulenotfounderror", "A3_compatibility", 1.0),
    ("validationerror", "A6_data_structure", 1.5),
    ("jsondecodeerror", "A6_data_structure", 1.5),
    ("outputparserexception", "A6_data_structure", 1.5),
    ("toolnotfound", "A2_tool_integration", 1.5),
    ("timeouterror", "A8_performance", 1.5),
    ("memoryerror", "A8_performance", 1.5),
    ("ratelimiterror", "A8_performance", 1.5),
    ("connectionerror", "A8_performance", 1.2),
    ("connectionrefused", "A7_configuration", 1.5),
    ("filenotfounderror", "A7_configuration", 1.2),
]

STAGE_FROM_A = {
    "A1_functionality": "C4_inference",
    "A2_tool_integration": "C5_tool_execution",
    "A3_compatibility": "C2_construction",
    "A4_communication": "C6_handoff",
    "A5_context_memory": "C3_prompt_assembly",
    "A6_data_structure": "C7_output_parsing",
    "A7_configuration": "C1_setup",
    "A8_performance": "C4_inference",
    "A9_safety": "C8_runtime_other",
    "A10_unknown": "C8_runtime_other",
}

TRACEBACK_RE = re.compile(r"traceback \(most recent call last\)", re.I)
EXC_RE = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception))\b")


@dataclass
class Labelled:
    failure_type: str
    type_confidence: float
    type_scores: dict[str, float]
    evidence_span: str
    cause_class: str
    cause_secondary: str
    cause_confidence: float
    cause_evidence_grade: str
    lifecycle_stage: str
    severity: str
    detection_point: str
    matched_rules: list[str] = field(default_factory=list)


class FailureLabeller:
    """Rule-based labeller over the five taxonomy dimensions."""

    def __init__(self, tax: Taxonomy | None = None, min_score: float = 1.9,
                 tool_override: float = 2.6) -> None:
        self.tax = tax or Taxonomy()
        self.min_score = min_score
        self.tool_override = tool_override
        self._a = {k: [(re.compile(p, re.I), w) for p, w in v]
                   for k, v in A_PATTERNS.items()}
        self._b = {k: [(re.compile(p, re.I), w) for p, w in v]
                   for k, v in B_PATTERNS.items()}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _score(text: str, patterns: list[tuple[re.Pattern, float]]
               ) -> tuple[float, str, int]:
        total = 0.0
        best_span = ""
        hits = 0
        for rx, w in patterns:
            m = rx.search(text)
            if m:
                hits += 1
                total += w
                if w >= 1.8 and not best_span:
                    start = max(0, m.start() - 70)
                    end = min(len(text), m.end() + 70)
                    best_span = " ".join(text[start:end].split())
        return total, best_span, hits

    def label_type(self, text: str) -> tuple[str, float, dict[str, float], str, list[str]]:
        low = text.lower()
        scores = {code: 0.0 for code in self._a}
        spans: dict[str, str] = {}
        rules: list[str] = []

        # The title and opening paragraph describe the failure in the reporter's
        # own words; traceback text further down is incidental. Signals are
        # therefore weighted by proximity: title > opening > remainder.
        title = text.split("\n", 1)[0][:300]
        opening = text[:900]

        for code, pats in self._a.items():
            s, span, hits = self._score(text, pats)
            t_s, t_span, t_hits = self._score(title, pats)
            o_s, o_span, _ = self._score(opening, pats)
            scores[code] += s + 0.85 * t_s + 0.35 * max(0.0, o_s - t_s)
            spans[code] = t_span or span or o_span
            if hits:
                rules.append(f"A:{code}:{hits}hits")

        # structural exception evidence
        for needle, code, w in EXCEPTION_RULES:
            if needle in low:
                scores[code] += w
                rules.append(f"EXC:{needle}->{code}")

        # disambiguation: a missing third-party package is a setup problem, while
        # a missing framework-internal symbol is an API-contract problem.
        if "no module named" in low or "modulenotfounderror" in low:
            mods = re.findall(r"(?:no module named|modulenotfounderror:?)\s*'?([\w\.\-]+)'?", low)
            frameworkish = any(
                any(k in m for k in ("crewai", "autogen", "langgraph", "llama_index",
                                     "llamaindex", "metagpt", "agents", "openai"))
                for m in mods)
            if re.search(r"pip install|requirements|poetry|conda install", low):
                scores["A7_configuration"] += 2.0
                scores["A3_compatibility"] -= 1.0
                rules.append("DISAMB:install-context->A7")
            elif frameworkish:
                scores["A3_compatibility"] += 1.5
                scores["A7_configuration"] -= 0.5
                rules.append("DISAMB:framework-symbol->A3")
            elif mods:
                scores["A7_configuration"] += 3.2
                scores["A3_compatibility"] *= 0.45
                rules.append("DISAMB:third-party-package->A7")

        # a proposal or documentation-only report is not a failure record
        title_low = text.split("\n", 1)[0].lower()
        if re.match(r"\s*(proposal|feature|feat|rfc|add |can you|would it be|"
                    r"docs?[\(:]|documentation)", title_low):
            if not TRACEBACK_RE.search(text):
                return ("A10_unknown", 0.30, scores, "",
                        rules + ["PRE:proposal-or-doc->A10"])

        # a traceback with no structural match is at least a runtime failure
        if TRACEBACK_RE.search(text) and max(scores.values()) < self.min_score:
            scores["A1_functionality"] += 1.0
            rules.append("HEUR:bare-traceback")

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_code, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0

        # Rule R2: tool interface failures beat generic compatibility when both fire
        if (scores["A2_tool_integration"] >= 2.0
                and scores["A2_tool_integration"] >= 0.60 * max(top, 1e-9)
                and top_code != "A2_tool_integration"
                and top_code in ("A3_compatibility", "A6_data_structure", "A1_functionality")):
            top_code, top = "A2_tool_integration", scores["A2_tool_integration"]
            rules.append("R2:tool-precedence")

        if top < self.min_score:
            # R4: a substantive failure report with no structural signal is most
            # plausibly a functional defect, but it is reported with low
            # confidence so the sensitivity analysis can separate it.
            if len(text) >= 300:
                return ("A1_functionality", 0.33, scores,
                        spans.get("A1_functionality", ""),
                        rules + ["R4:residual-functionality"])
            return ("A10_unknown", 0.25, scores, "", rules + ["R4:below-threshold"])

        margin = (top - second) / max(top, 1e-9)
        share = top / max(sum(scores.values()), 1e-9)
        conf = 0.42 + 0.34 * share + 0.22 * min(margin, 1.0)
        conf = round(min(max(conf, 0.30), 0.97), 3)
        return top_code, conf, scores, spans.get(top_code, ""), rules

    def label_cause(self, text: str, ftype: str) -> tuple[str, str, float, str]:
        scores: dict[str, float] = {}
        for code, pats in self._b.items():
            s, _, _ = self._score(text, pats)
            scores[code] = s
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_code, top = ranked[0]
        second_code = ranked[1][0] if len(ranked) > 1 else "B10_unknown"
        second = ranked[1][1] if len(ranked) > 1 else 0.0

        if top < 1.6:
            # fall back to a type-implied cause, graded as hypothesised
            implied = {
                "A3_compatibility": "B2_api_version_drift",
                "A7_configuration": "B3_configuration_error",
                "A2_tool_integration": "B7_tool_environment",
                "A5_context_memory": "B6_context_management",
                "A4_communication": "B1_framework_defect",
                "A6_data_structure": "B5_model_limitation",
            }.get(ftype, "B10_unknown")
            return implied, "B10_unknown", 0.30, "hypothesised"

        conf = round(min(0.95, 0.45 + 0.4 * (top / max(sum(scores.values()), 1e-9))
                         + 0.15 * ((top - second) / max(top, 1e-9))), 3)
        if TRACEBACK_RE.search(text) and top >= 2.4:
            grade = "demonstrated"
        elif top >= 2.0:
            grade = "supported"
        else:
            grade = "hypothesised"
        return top_code, second_code if second >= 1.6 else "B10_unknown", conf, grade

    @staticmethod
    def label_stage(text: str, ftype: str) -> str:
        low = text.lower()
        if ftype == "A3_compatibility" and re.search(r"pip install|install|requirements", low):
            return "C1_setup"
        return STAGE_FROM_A.get(ftype, "C8_runtime_other")

    @staticmethod
    def label_severity(text: str, ftype: str) -> str:
        low = text.lower()
        if TRACEBACK_RE.search(text) or re.search(
                r"\b(crash|exception|fails? to start|cannot (run|start|import))\b", low):
            return "D1_blocking"
        if re.search(r"\b(incorrect|wrong|silent|no error|but returns|produces? the wrong)\b", low):
            return "D2_incorrect_output"
        if re.search(r"\b(workaround|sometimes|partial|intermittent|degraded)\b", low):
            return "D3_degraded"
        if re.search(r"\b(warning|log noise|cosmetic|typo in (docs|message))\b", low):
            return "D4_minor"
        return "D3_degraded"

    @staticmethod
    def label_detection(text: str, ftype: str) -> str:
        low = text.lower()
        if ftype == "A7_configuration":
            return "E5_configuration_validation"
        if TRACEBACK_RE.search(text):
            return "E1_framework_runtime"
        if re.search(r"\b(test|assert|pytest|unit test|evaluation)\b", low):
            return "E2_external_test"
        if re.search(r"\b(monitor|alert|logging|metrics|production)\b", low):
            return "E4_production_monitoring"
        return "E3_human_observation"

    # ------------------------------------------------------------------ public
    def label(self, text: str) -> Labelled:
        ftype, conf, scores, span, rules = self.label_type(text)
        cause, secondary, cconf, grade = self.label_cause(text, ftype)
        return Labelled(
            failure_type=ftype,
            type_confidence=conf,
            type_scores={k: round(v, 3) for k, v in scores.items()},
            evidence_span=span[:400],
            cause_class=cause,
            cause_secondary=secondary,
            cause_confidence=cconf,
            cause_evidence_grade=grade,
            lifecycle_stage=self.label_stage(text, ftype),
            severity=self.label_severity(text, ftype),
            detection_point=self.label_detection(text, ftype),
            matched_rules=rules,
        )

    def label_batch(self, texts: Iterable[str]) -> list[Labelled]:
        return [self.label(t) for t in texts]


def is_failure_record(title: str, body: str, labels: list[str]) -> tuple[bool, str]:
    """Decide whether an issue reports an observed failure.

    Returns (keep, reason). Records are never dropped silently: the reason is
    stored for every exclusion so the paper can report an exclusion count.
    """
    low = (title + "\n" + body).lower()
    label_set = {l.lower() for l in labels}
    if TRACEBACK_RE.search(low) or EXC_RE.search(title + "\n" + body):
        return True, "exception_or_traceback"
    if re.search(r"\b(error|errors?|fail(s|ed|ing|ure)?|crash(es|ed)?|bug|bugs|"
                 r"broken|exception|invalid|wrong|doesn't work|not work)\b", low):
        if "feature request" in label_set and not re.search(r"\b(error|crash|exception)\b", low):
            return False, "feature_request"
        if "question" in label_set and not re.search(r"\b(error|crash|exception)\b", low):
            return False, "question_only"
        return True, "failure_lexicon"
    if label_set & {"bug", "bug report"}:
        return True, "labelled_bug"
    return False, "no_failure_signal"

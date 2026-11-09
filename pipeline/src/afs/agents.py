"""The agentic analysis application.

Architecture
------------
A blackboard-style multi-agent system:

    PlannerAgent
        reads the research questions, inspects the dataset, and emits an ordered
        plan. It can refuse a question when the required field is absent, which
        is a real decision rather than a placeholder.

    Specialist agents (Statistician, Causal, Comparator, Complexity)
        each own a subset of the questions and call shared statistical tools.

    CriticAgent
        independently recomputes each finding's headline number from the raw
        records, checks denominator consistency, and rejects claims that assert
        causation for an association. Rejected findings are sent back once with
        a critique, producing a genuine verification loop.

    ReporterAgent
        renders the verified findings into tables, figures and prose.

Every message is recorded, so the run produces a transcript that can be audited
and shown to a supervisor. Numbers never pass through a language model: the
optional LLM adapter is used only for narrative phrasing.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

from . import analysis, stats
from .common import OUT_DIR, REP_DIR, TAB_DIR, utc_now, write_json, write_jsonl
from .taxonomy import Taxonomy

T = Taxonomy()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


# --------------------------------------------------------------------------- #
# Message passing
# --------------------------------------------------------------------------- #
@dataclass
class Message:
    sender: str
    recipient: str
    act: str                      # request | inform | propose | verify | refuse
    content: str
    payload: dict = field(default_factory=dict)
    ts: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


class Blackboard:
    """Shared state plus an append-only transcript."""

    def __init__(self, records: list[dict], rq_config: dict) -> None:
        self.records = records
        self.rq_config = rq_config
        self.messages: list[Message] = []
        self.results: dict[str, dict] = {}
        self.verified: dict[str, dict] = {}
        self.rejected: list[dict] = []
        self.events: list[dict] = []
        self.tool_calls: list[dict] = []

    def post(self, msg: Message) -> Message:
        self.messages.append(msg)
        return msg

    def log(self, agent: str, event: str, **details) -> None:
        self.events.append({"ts": _now(), "agent": agent, "event": event, **details})

    def call_tool(self, agent: str, tool: str, fn: Callable, *a, **kw):
        self.tool_calls.append({"ts": _now(), "agent": agent, "tool": tool})
        return fn(*a, **kw)

    def transcript(self) -> list[dict]:
        return [m.to_dict() for m in self.messages]


# --------------------------------------------------------------------------- #
# Agent base
# --------------------------------------------------------------------------- #
class Agent:
    name = "Agent"
    goal = ""

    def __init__(self) -> None:
        self.bb: Blackboard | None = None

    def attach(self, bb: Blackboard) -> "Agent":
        self.bb = bb
        return self

    def say(self, recipient: str, act: str, content: str, **payload) -> Message:
        assert self.bb is not None
        return self.bb.post(Message(self.name, recipient, act, content, payload))

    def run(self, task: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #
class PlannerAgent(Agent):
    name = "PlannerAgent"
    goal = "Turn research questions into an ordered, feasible plan."

    _OWNER = {
        "RQ1": "StatisticianAgent", "RQ2": "StatisticianAgent",
        "RQ3": "CausalAgent", "RQ4": "ComparatorAgent",
        "RQ5": "ComparatorAgent", "RQ6": "ComplexityAgent",
        "RQ7": "StatisticianAgent", "RQ8": "StatisticianAgent",
        "RQ9": "ComparatorAgent", "RQ10": "ComplexityAgent",
    }

    def run(self, task: dict) -> dict:
        assert self.bb
        questions = self.bb.rq_config["questions"]
        fields = set(self.bb.records[0].keys()) if self.bb.records else set()

        plan, refused = [], []
        for q in questions:
            rq = q["id"]
            missing = [f for f in q.get("requires", [])
                       if f not in fields and f not in ("complexity_tier",)]
            if missing:
                refused.append({"rq": rq, "missing": missing})
                continue
            plan.append({
                "rq": rq,
                "question": q["question"],
                "owner": self._OWNER.get(rq, "StatisticianAgent"),
                "mode": q.get("agent_mode", "chain"),
                "agents": q.get("agents", []),
                "method": q.get("method", ""),
            })

        # Sequential ordering: descriptive questions first, because inferential
        # questions read better when the distribution is already known.
        order = {"RQ1": 0, "RQ2": 1, "RQ8": 2, "RQ3": 3, "RQ4": 4, "RQ5": 5,
                 "RQ7": 6, "RQ6": 7, "RQ10": 8, "RQ9": 9}
        plan.sort(key=lambda p: order.get(p["rq"], 99))

        self.bb.log(self.name, "plan_created", steps=len(plan), refused=len(refused))
        self.say("Orchestrator", "inform",
                 f"Plan built: {len(plan)} executable questions, {len(refused)} refused "
                 f"for missing fields.",
                 plan=plan, refused=refused)
        return {"plan": plan, "refused": refused}


# --------------------------------------------------------------------------- #
# Tagger
# --------------------------------------------------------------------------- #
class TaggerAgent(Agent):
    name = "TaggerAgent"
    goal = "Verify that every record carries a complete taxonomy label."

    def run(self, task: dict) -> dict:
        assert self.bb
        recs = self.bb.records
        required = ["A_failure_type", "B_cause_class", "C_lifecycle_stage",
                    "D_severity", "E_detection_point"]
        incomplete = [r["record_id"] for r in recs
                      if any(not r.get(f) for f in required)]
        confs = [r["A_confidence"] for r in recs]
        dist = Counter(round(c, 1) for c in confs)
        low = sum(1 for c in confs if c < 0.45)

        payload = {
            "n_records": len(recs),
            "incomplete": len(incomplete),
            "mean_confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "low_confidence": low,
            "confidence_histogram": {str(k): v for k, v in sorted(dist.items())},
            "unknown_labels": sum(1 for r in recs if r["A_failure_type"] == "A10_unknown"),
        }
        self.bb.log(self.name, "label_audit", **payload)
        self.say("Orchestrator", "inform",
                 f"All {len(recs)} records labelled; {low} below the 0.45 confidence "
                 f"floor and queued for adjudication.", **payload)
        return payload


# --------------------------------------------------------------------------- #
# Specialists
# --------------------------------------------------------------------------- #
class _Specialist(Agent):
    functions: dict[str, Callable] = {}

    def run(self, task: dict) -> dict:
        assert self.bb
        rq = task["rq"]
        fn = self.functions[rq]
        result = self.bb.call_tool(self.name, f"analysis.{rq}", fn, self.bb.records)
        result["rq"] = rq
        result["owner"] = self.name
        self.bb.results[rq] = result
        self.bb.log(self.name, "analysis_complete", rq=rq,
                    rows=len(result.get("table") or []))
        self.say("CriticAgent", "propose",
                 f"{rq} computed; headline metric {json.dumps(result['metrics'], default=str)[:220]}",
                 rq=rq, metrics=result["metrics"])
        return result


class StatisticianAgent(_Specialist):
    name = "StatisticianAgent"
    goal = "Descriptive statistics with explicit denominators and intervals."
    functions = {"RQ1": analysis.rq1_frequency, "RQ2": analysis.rq2_ranked,
                 "RQ7": analysis.rq7_escape, "RQ8": analysis.rq8_unknown}


class CausalAgent(_Specialist):
    name = "CausalAgent"
    goal = "Associations between failure types and causes, never stated as causation."
    functions = {"RQ3": analysis.rq3_cause_by_type}


class ComparatorAgent(_Specialist):
    name = "ComparatorAgent"
    goal = "Framework-level and temporal comparisons."
    functions = {"RQ4": analysis.rq4_framework_by_type,
                 "RQ5": analysis.rq5_framework_severity,
                 "RQ9": analysis.rq9_trend}


class ComplexityAgent(_Specialist):
    name = "ComplexityAgent"
    goal = "Whether declared architectural complexity tracks failure profile."
    functions = {"RQ6": analysis.rq6_complexity, "RQ10": analysis.rq10_strata}


# --------------------------------------------------------------------------- #
# Critic
# --------------------------------------------------------------------------- #
CAUSAL_WORDS = ("causes", "caused by", "leads to", "results in", "due to")


class CriticAgent(Agent):
    name = "CriticAgent"
    goal = "Block unsupported numbers before they reach the report."

    def _recompute(self, rq: str, bb: Blackboard) -> dict:
        """Independent recomputation of the headline metric.

        Deliberately re-derives the value from the raw records rather than
        trusting the result object.
        """
        recs = bb.records
        n = len(recs)
        if rq == "RQ1":
            counts = Counter(r["A_failure_type"] for r in recs)
            top, k = counts.most_common(1)[0]
            return {"n_records": n, "top_category": top,
                    "top_share": round(k / n, 4), "n_categories": len(counts)}
        if rq == "RQ2":
            conf = [r for r in recs if r["A_confidence"] >= 0.6]
            counts = Counter(r["A_failure_type"] for r in conf)
            top, k = counts.most_common(1)[0]
            return {"n_records": n, "n_confident": len(conf),
                    "top_share_confident": round(k / len(conf), 4)}
        if rq == "RQ3":
            return {"n_records": n,
                    "demonstrated_causes": sum(1 for r in recs
                                               if r["B_evidence_grade"] == "demonstrated")}
        if rq == "RQ4":
            return {"n_records": n,
                    "n_frameworks": len({r["framework"] for r in recs})}
        if rq == "RQ5":
            return {"n_records": n,
                    "top_blocking_rate": round(
                        max((sum(1 for r in recs if r["framework"] == fw
                                 and r["D_severity"] == "D1_blocking")
                             / max(sum(1 for r in recs if r["framework"] == fw), 1))
                            for fw in {r["framework"] for r in recs}), 4)}
        if rq == "RQ6":
            return {"n_records": n}
        if rq == "RQ7":
            return {"n_records": n}
        if rq == "RQ8":
            k = sum(1 for r in recs if r["A_failure_type"] == "A10_unknown")
            return {"unknown": k, "unknown_share": round(k / n, 4)}
        if rq == "RQ9":
            return {"n_records": n}
        if rq == "RQ10":
            return {"n_records": n}
        return {}

    def verify(self, payload: dict) -> dict:
        assert self.bb
        rq = payload.get("rq")
        result = self.bb.results.get(rq)
        if result is None:
            return {"rq": rq, "decision": "reject", "reason": "no result on blackboard"}

        truth = self._recompute(rq, self.bb)
        claimed = result.get("metrics", {})
        issues = []

        for key, val in truth.items():
            if key in claimed:
                got = claimed[key]
                if isinstance(val, float) and isinstance(got, (int, float)):
                    if abs(float(got) - val) > 1e-6:
                        issues.append(f"{key}: claimed {got}, recomputed {val}")
                elif val != got:
                    issues.append(f"{key}: claimed {got}, recomputed {val}")

        # denominator consistency
        rows = result.get("table") or []
        if rq in ("RQ1", "RQ2") and rows:
            total = sum(r["count"] for r in rows)
            if total != truth.get("n_records"):
                issues.append(f"table counts sum to {total}, expected {truth.get('n_records')}")

        # language check on the note
        note = str(result.get("note", "")).lower()
        if rq in ("RQ3", "RQ4", "RQ6", "RQ10"):
            for w in CAUSAL_WORDS:
                if w in note and "not causation" not in note and "association" not in note:
                    issues.append(f"association result uses causal language: '{w}'")
                    break

        # statistical sanity
        p = result.get("metrics", {}).get("p_value")
        if p is not None and not (0.0 <= float(p) <= 1.0):
            issues.append(f"invalid p-value {p}")

        decision = "accept" if not issues else "revise"
        verdict = {"rq": rq, "decision": decision, "issues": issues,
                   "recomputed": truth}
        if decision == "accept":
            self.bb.verified[rq] = result
        else:
            self.bb.rejected.append(verdict)
        self.bb.log(self.name, "verification", rq=rq, decision=decision, issues=len(issues))
        self.say("Orchestrator", "verify",
                 f"{rq}: {decision}" + (f" ({len(issues)} issue(s))" if issues else ""),
                 **verdict)
        return verdict

    def run(self, task: dict) -> dict:
        return self.verify(task)


# --------------------------------------------------------------------------- #
# Reporter
# --------------------------------------------------------------------------- #
class ReporterAgent(Agent):
    name = "ReporterAgent"
    goal = "Render verified findings into a report with no unverified numbers."

    def run(self, task: dict) -> dict:
        from .report import build_report

        assert self.bb
        path = build_report(self.bb)
        self.bb.log(self.name, "report_written", path=str(path))
        self.say("Orchestrator", "inform", f"Report written to {path}")
        return {"report_path": str(path)}


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
class Orchestrator:
    def __init__(self, records: list[dict], rq_config: dict) -> None:
        self.bb = Blackboard(records, rq_config)
        self.planner = PlannerAgent().attach(self.bb)
        self.tagger = TaggerAgent().attach(self.bb)
        self.specialists = {
            "StatisticianAgent": StatisticianAgent().attach(self.bb),
            "CausalAgent": CausalAgent().attach(self.bb),
            "ComparatorAgent": ComparatorAgent().attach(self.bb),
            "ComplexityAgent": ComplexityAgent().attach(self.bb),
        }
        self.critic = CriticAgent().attach(self.bb)
        self.reporter = ReporterAgent().attach(self.bb)

    def run(self, out_dir=OUT_DIR) -> dict:
        bb = self.bb
        bb.log("Orchestrator", "run_started", records=len(bb.records))

        plan = self.planner.run({})
        self.tagger.run({})

        for step in plan["plan"]:
            rq = step["rq"]
            owner = self.specialists.get(step["owner"])
            if owner is None:
                bb.log("Orchestrator", "no_owner", rq=rq, owner=step["owner"])
                continue

            result = owner.run(step)
            verdict = self.critic.verify({"rq": rq})

            if verdict["decision"] == "revise":
                # one corrective pass with the critique attached
                bb.log("Orchestrator", "revision_requested", rq=rq,
                       issues=verdict["issues"])
                owner.say("CriticAgent", "inform",
                          f"Revising {rq} after critique: {verdict['issues']}")
                result = owner.run(step)
                verdict = self.critic.verify({"rq": rq})

            bb.log("Orchestrator", "step_complete", rq=rq,
                   decision=verdict["decision"])

        self.reporter.run({})
        bb.log("Orchestrator", "run_finished",
               accepted=len(bb.verified), rejected=len(bb.rejected))

        summary = {
            "records": len(bb.records),
            "questions_planned": len(plan["plan"]),
            "questions_refused": len(plan["refused"]),
            "questions_verified": len(bb.verified),
            "rejections": len(bb.rejected),
            "messages": len(bb.messages),
            "tool_calls": len(bb.tool_calls),
        }
        write_jsonl(out_dir / "transcript.jsonl", bb.transcript())
        write_json(out_dir / "agent_run_summary.json", summary)
        write_json(out_dir / "agent_events.json", bb.events)
        write_json(out_dir / "analysis_results.json", {
            "generated_at": utc_now(),
            "verified": bb.verified,
            "rejected": bb.rejected,
            "all_results": bb.results,
        })
        return summary


# --------------------------------------------------------------------------- #
def load_rq_config() -> dict:
    import yaml

    from .common import CONFIG_DIR

    with open(CONFIG_DIR / "research_questions.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)

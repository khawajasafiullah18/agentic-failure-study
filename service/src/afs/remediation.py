"""Turn a taxonomy label into an action plan.

The taxonomy says what kind of failure something is. A supervisor holding a real
traceback needs the next three things to do, in order, and an honest statement
of how much the label can be trusted.

Every recommendation here is derived from the dimension that was actually
labelled, plus the failure mode the study measured. Nothing is generic advice:
the "silent failure" recommendations exist because roughly a third of the corpus
was never caught by the framework runtime, and the tool recommendations exist
because tool-interface failures are the fourth largest category.

This module is deliberately data, not inference. It produces the same plan for
the same label, so a plan can be argued with.
"""
from __future__ import annotations

from .taxonomy import Taxonomy

T = Taxonomy()

_ESCAPE_CACHE: dict[str, str] = {}


def _escape_text() -> str:
    """Measured silent-failure share, or a defensible phrase if unavailable.

    The figure is read from the verified results rather than typed here, so the
    advice cannot quote a stale percentage after the corpus is relabelled.
    """
    if "text" in _ESCAPE_CACHE:
        return _ESCAPE_CACHE["text"]
    text = "about a third"
    try:
        from .common import OUT_DIR, read_json

        res = read_json(OUT_DIR / "analysis_results.json")
        block = (res.get("verified") or res.get("all_results") or {}).get("RQ7") or {}
        share = (block.get("metrics") or {}).get("escape_share")
        if isinstance(share, (int, float)):
            text = f"{share:.1%}"
    except Exception:
        pass
    _ESCAPE_CACHE["text"] = text
    return text

# Each entry: what to do now (stop the bleeding), next (fix the cause), and the
# guardrail that would have caught it. Written for agent systems specifically.
PLAYBOOK: dict[str, dict[str, list[str]]] = {
    "A1_functionality": {
        "now": [
            "Re-run the failing step alone with the exact prompt and tool results; "
            "the failure is usually a single turn, not the whole chain.",
            "Log the model output at that turn. If it is plausible but wrong, treat it "
            "as an output-correctness bug, not an exception.",
        ],
        "next": [
            "Assert on the step's output (schema plus one semantic check) instead of "
            "trusting that it completed.",
            "If the step delegates reasoning, give it a narrower instruction and an "
            "explicit success criterion. Broad instructions are where adherence slips.",
        ],
        "guardrail": [
            "Keep a fixed evaluation set of ~20 representative tasks and fail CI when "
            "the passing count drops.",
        ],
    },
    "A2_tool_integration": {
        "now": [
            "Log the tool name, the JSON arguments, and the raw response for every "
            "call. Most of these failures are visible in the arguments.",
            "Check the tool is in the registry the model was given, under the same name "
            "and schema the model used.",
        ],
        "next": [
            "Validate arguments against the tool's schema before dispatch, and return "
            "the validation error to the model as an observation rather than raising.",
            "Give the model the tool's error contract (what a failure looks like) so it "
            "can retry differently instead of repeating the same call.",
        ],
        "guardrail": [
            "One contract test per tool: schema round-trip, error shape, and a timeout.",
        ],
    },
    "A3_compatibility": {
        "now": [
            "Print the installed versions of the framework and its plugins, and diff "
            "them against the release notes for the version that broke.",
            "Reproduce in a clean environment with pinned versions before editing code.",
        ],
        "next": [
            "Pin exact versions and isolate optional dependencies; an unpinned "
            "framework is a moving target.",
            "If an internal import moved, depend on the public API, not the internal "
            "symbol.",
        ],
        "guardrail": [
            "CI matrix over the supported minor versions with an import smoke test.",
        ],
    },
    "A4_communication": {
        "now": [
            "Log the selected speaker and the turn count; find the turn where routing "
            "started repeating or stopped early.",
            "Dump the handoff payload. An empty or truncated handoff is the usual "
            "cause of a downstream agent doing nothing.",
        ],
        "next": [
            "Make termination conditions explicit (max turns plus a completion check), "
            "not implied by the prompt.",
            "Validate the handoff payload against a schema before the next agent reads it.",
        ],
        "guardrail": [
            "Transcript assertion in tests: no speaker more than twice in a row, every "
            "handoff carries required fields.",
        ],
    },
    "A5_context_memory": {
        "now": [
            "Measure tokens per step and find the step where the window is exceeded or "
            "history is dropped.",
            "Check whether the state lives inside the conversation. If it does, any "
            "compaction loses it.",
        ],
        "next": [
            "Keep task state outside the context and pass an explicit summary into each "
            "step.",
            "Compact by summarising completed steps, not by truncating the tail.",
        ],
        "guardrail": [
            "Token budget alarm at 70% of the window, and a test that state survives "
            "forced compaction.",
        ],
    },
    "A6_data_structure": {
        "now": [
            "Capture the raw model output that failed to parse. Do not re-prompt before "
            "you have it, or you lose the evidence.",
            "Check the parser against the actual output: trailing prose, markdown "
            "fences, and missing fields account for most cases.",
        ],
        "next": [
            "Use structured output or a function schema instead of parsing free text.",
            "On parse failure, retry once with the validation error attached, then fail "
            "loudly rather than silently substituting a default.",
        ],
        "guardrail": [
            "Schema validation at every boundary; reject unknown fields instead of "
            "dropping them.",
        ],
    },
    "A7_configuration": {
        "now": [
            "Check the environment the process actually sees: env vars, key scope, "
            "network egress, and whether Docker passed them through.",
            "Confirm the credential is valid and has the scope the call needs, not just "
            "that it exists.",
        ],
        "next": [
            "Validate configuration at startup and refuse to run on a missing or empty "
            "value; silent defaults hide this class.",
        ],
        "guardrail": [
            "Startup self-check that exercises each external dependency once, plus a "
            "config smoke test in CI.",
        ],
    },
    "A8_performance": {
        "now": [
            "Separate timeout from rate limit from memory pressure using the response "
            "body and status code; the fix differs for each.",
            "Find whether the cost is per step or in one oversized call.",
        ],
        "next": [
            "Add backoff with jitter for rate limits and a per-step time budget for "
            "latency; cap context growth for memory.",
        ],
        "guardrail": [
            "Track p95 latency and 429 rate per step, and alert on the first sustained "
            "rise.",
        ],
    },
    "A9_safety": {
        "now": [
            "Treat all external text (tool results, retrieved documents, user content) "
            "as untrusted, and find the payload that changed behaviour.",
            "Check what the agent could reach when it misbehaved: tools, files, "
            "credentials, network.",
        ],
        "next": [
            "Allowlist tools per role and require confirmation for destructive actions.",
            "Keep secrets out of the model's context; the model should never see a key "
            "it does not need.",
        ],
        "guardrail": [
            "An injection test set run in CI, and an output filter on anything that "
            "leaves the system.",
        ],
    },
    "A10_unknown": {
        "now": [
            "Do not force a label. Keep the case and record what evidence is missing.",
            "Get a minimal reproduction: full traceback, framework version, and the "
            "smallest prompt that triggers it.",
        ],
        "next": [
            "Add the missing evidence to the report; most unknowns in this corpus are "
            "missing versions or a missing traceback.",
        ],
        "guardrail": [
            "Watch the unknown rate. If it climbs above ~3%, the codebook needs a new "
            "category rather than better guessing.",
        ],
    },
}

CAUSE_ADDENDA: dict[str, list[str]] = {
    "B1_framework_defect": [
        "Search the tracker for the same internal error before working around it; a "
        "maintainer fix is cheaper than a workaround you will have to remove.",
    ],
    "B2_api_version_drift": [
        "Write the failing call against the pinned version's signature, and add a "
        "test that fails if the signature changes.",
    ],
    "B3_configuration_error": [
        "Make the missing value fail at startup with the variable's name in the error.",
    ],
    "B4_specification_ambiguity": [
        "Record the behaviour the documentation implied. If it contradicts the "
        "implementation, that is a documentation bug worth reporting.",
    ],
    "B5_model_limitation": [
        "Narrow the task, add a worked example, or move the step to a stronger model. "
        "Prompt wording alone rarely fixes an instruction-following limit.",
    ],
    "B6_context_management": [
        "Move long-lived state out of the prompt into a store the step can query.",
    ],
    "B7_tool_environment": [
        "Mock the tool in tests and assert the agent's behaviour when it is down; "
        "unavailable dependencies are a normal condition, not an exception.",
    ],
    "B8_application_logic": [
        "Add a unit test at the boundary where your code meets the framework.",
    ],
    "B9_expectation_mismatch": [
        "If the behaviour is by design, fix the expectation and document it; otherwise "
        "this is not the failure you are looking for.",
    ],
}


def build_plan(failure_type: str, cause_class: str, lifecycle_stage: str,
               severity: str, detection_point: str,
               confidence: float) -> dict:
    """Assemble the plan for one labelled case."""
    play = PLAYBOOK.get(failure_type, PLAYBOOK["A10_unknown"])
    now = list(play["now"])
    nxt = list(play["next"])
    guards = list(play["guardrail"])

    # Silent wrong output is the most expensive mode in the corpus, so it is
    # promoted to the top of the plan rather than left as a footnote.
    if severity == "D2_incorrect_output":
        now.insert(0, "Nothing raised an error, so start from the output: capture "
                      "what the user received and compare it to the contract. This "
                      "record is wrong output, not a crash.")
        guards.append(f"Add an output assertion. In this corpus {_escape_text()} of "
                      "failures reached a user without the runtime reporting them.")
    if detection_point in ("E3_human_observation", "E5_configuration_validation"):
        guards.append("The detection point was late or manual: add a check at the "
                      "step that produced the bad state, not at the end of the run.")

    addenda = CAUSE_ADDENDA.get(cause_class, [])
    if addenda:
        nxt.extend(addenda)

    caveats: list[str] = []
    if confidence < 0.45:
        caveats.append("Low confidence: the evidence is thin, so treat this as a "
                       "hypothesis and confirm it against the text before acting.")
    if failure_type == "A10_unknown":
        caveats.append("No category fits. That is a finding about the codebook, not "
                       "about your system; do not let it stop the triage.")
    if cause_class == "B10_unknown":
        caveats.append("The cause could not be inferred from the text. The type "
                       "dimension is still informative; the cause is not.")

    seen: set[str] = set()
    unique_now = [a for a in now if not (a in seen or seen.add(a))]
    return {
        "now": unique_now,
        "next": [a for a in nxt if a not in unique_now],
        "guardrail": guards,
        "caveats": caveats,
    }


def label_set(failure_type: str, cause_class: str, lifecycle_stage: str,
              severity: str, detection_point: str) -> list[dict]:
    """Human-readable labels for the five dimensions."""
    return [
        {"dimension": "A", "name": "Failure type", "code": failure_type,
         "label": T.label("A_failure_type", failure_type)},
        {"dimension": "B", "name": "Cause class", "code": cause_class,
         "label": T.label("B_cause_class", cause_class)},
        {"dimension": "C", "name": "Lifecycle stage", "code": lifecycle_stage,
         "label": T.label("C_lifecycle_stage", lifecycle_stage)},
        {"dimension": "D", "name": "Severity", "code": severity,
         "label": T.label("D_severity", severity)},
        {"dimension": "E", "name": "Detection point", "code": detection_point,
         "label": T.label("E_detection_point", detection_point)},
    ]

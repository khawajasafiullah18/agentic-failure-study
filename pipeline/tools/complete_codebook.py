"""One-off: complete the codebook so every code has a definition, an inclusion
rule and an explicit exclusion clause, in all five dimensions.

Dimension A already had them. B had definitions and signals but no boundaries;
C, D and E stored a single gloss per code. This script fills those in and
re-emits the YAML with its header intact. It is kept in the repository because
the boundary wording is a reviewable artefact, not a silent edit.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "configs" / "taxonomy.v1.yaml"

HEADER = """\
# Failure Taxonomy for Agentic and Multi-Agent Applications
# Codebook v1.0 -- frozen 2026-11-04; boundaries documented for all five
# dimensions 2026-11-08 (codes and patterns unchanged, so no label moves).
#
# Five orthogonal dimensions are coded independently for each failure record.
# A record is ONE publicly reported failure of an agentic application.
# Dimension A is single-label (primary). Dimension B is single-label (primary
# cause, with an optional secondary). C, D, E are single-label.
#
# Every code in every dimension carries a definition, an inclusion rule and an
# explicit "not this category" clause, because boundary ambiguity is the main
# source of low inter-rater agreement (see Zhu et al. 2026; Zhang et al. 2026).
"""

A_EXCLUDE_10 = [
    "The report names a mechanism that supports any other category",
    "The text is a feature request, question or documentation note rather "
    "than a failure, which is excluded from the corpus instead of coded here",
]

B_FILL = {
    "B1_framework_defect": (
        ["The fault is in the framework's own code path",
         "A maintainer confirms the defect or links a fix",
         "The same input fails only on one framework version"],
        ["The user's own agent code is at fault (B8)",
         "An upstream provider changed its API (B2)"]),
    "B2_api_version_drift": (
        ["Behaviour changes after an upgrade of the framework or a provider SDK",
         "A renamed, removed or newly required argument breaks existing code",
         "Pinning an older version resolves the report"],
        ["The version was never compatible with the documented requirement (B3)",
         "A bug present in all versions of the framework (B1)"]),
    "B3_configuration_error": (
        ["A required key, variable, path or credential is absent or malformed",
         "Installation, dependency resolution or container setup is incomplete",
         "The same code succeeds once the environment is corrected"],
        ["A missing internal symbol raised by an otherwise working install (B1)",
         "An external service that is down rather than misconfigured (B7)"]),
    "B4_specification_ambiguity": (
        ["The documented behaviour does not state what the reporter assumed",
         "Two reasonable readings of the API lead to the reported failure",
         "The fix is a documentation change rather than a code change"],
        ["The documentation is clear and the user misread it (B9)",
         "Nothing is documented because the feature does not exist (B9)"]),
    "B5_model_limitation": (
        ["The task is beyond the model's capability at the stated size or budget",
         "Output quality degrades with a known model weakness such as arithmetic",
         "The same prompt succeeds with a stronger model"],
        ["The model was given the wrong instructions (B8)",
         "The model was denied relevant context it could have used (B6)"]),
    "B6_context_management": (
        ["History, retrieved context or shared state is dropped or truncated",
         "The agent forgets an earlier instruction within the same run",
         "A checkpoint or resume path loses state"],
        ["The prompt as assembled was already wrong before any loss (B8)",
         "The provider rejected an oversized request (B7)"]),
    "B7_tool_environment": (
        ["A tool, service or network dependency is unavailable or rate limited",
         "The sandbox, filesystem or interpreter cannot perform the call",
         "The failure disappears when the dependency is restored"],
        ["The tool works but was called with wrong arguments (B8)",
         "The tool is not installed because setup was incomplete (B3)"]),
    "B8_application_logic": (
        ["The user's own orchestration, prompt or glue code is incorrect",
         "A wrong default, branch or loop bound is visible in the report",
         "Correcting the application code resolves the failure"],
        ["The framework itself behaves contrary to its documentation (B1)",
         "The application is correct but the model cannot do the task (B5)"]),
    "B9_expectation_mismatch": (
        ["The reported behaviour is the documented or intended behaviour",
         "The feature is unsupported and the report is a request for it",
         "Maintainers close the report as expected behaviour"],
        ["The documentation genuinely contradicts the behaviour (B4)",
         "The failure is real and the cause is a defect (B1 or B8)"]),
    "B10_unknown": (
        ["No mechanism is stated and none can be inferred from the text",
         "The cause is recorded as hypothesised rather than identified"],
        ["Any category above is supported by the text, however briefly"]),
}

C_FILL = {
    "C1_setup": (
        "The failure occurred before any agent code ran: installing the package, "
        "resolving dependencies, or satisfying an environment or credential "
        "precondition.",
        ["Dependency resolution or package installation fails",
         "A credential, API key or environment variable is absent at start-up",
         "A required system library or container layer is missing"],
        ["A framework-internal symbol is missing in an otherwise working install "
         "(compatibility, dimension A)",
         "A model call fails after start-up succeeded (C4)"]),
    "C2_construction": (
        "Building the objects that define the workflow - agents, teams, graphs, "
        "tools, routers - failed, or the object was constructed in an invalid "
        "configuration.",
        ["An agent, team or graph constructor raises",
         "Tool registration or its schema is rejected at build time",
         "An invalid graph topology is rejected before execution"],
        ["Credentials or dependencies are missing before construction (C1)",
         "An agent-to-agent exchange fails after the workflow is running (C6)"]),
    "C3_prompt_assembly": (
        "The failure occurred while composing the input to a model call: system "
        "prompt, role descriptions, the message list, or retrieved context.",
        ["A prompt template renders incorrectly or with missing fields",
         "Assembled context exceeds the window before the request is sent",
         "The message list is malformed before it reaches the provider"],
        ["Context is lost between calls during the run (dimension A: context "
         "and memory)",
         "The provider rejects the request after it was sent (C4)"]),
    "C4_inference": (
        "The failure occurred in the model call itself: the provider rejected "
        "the request, the response was unusable, or the response content is "
        "wrong.",
        ["The provider returns an error, times out, or rate limits the call",
         "The model returns an incomplete, wrong or hallucinated answer",
         "The token limit is hit during generation"],
        ["Composing the request failed before sending (C3)",
         "A well-formed response could not be parsed into the expected schema "
         "(C7)"]),
    "C5_tool_execution": (
        "The failure occurred at the tool boundary: the wrong tool was selected, "
        "its arguments were wrong, it was unavailable, or its result was "
        "unusable.",
        ["The selected tool does not exist or is not registered at call time",
         "Arguments fail the tool's own schema",
         "The external service returns an error to the tool"],
        ["A tool object could not be constructed at all (C2)",
         "The tool returned successfully and parsing its result failed (C7)"]),
    "C6_handoff": (
        "Passing control or state between agents failed: the wrong agent was "
        "selected, the handoff never happened, or the message was rejected by "
        "the receiver.",
        ["Speaker selection loops or picks the same agent repeatedly",
         "A delegation never returns to the caller",
         "The receiving agent rejects the handoff payload"],
        ["A single agent looping with no second agent (C4)",
         "State is lost between calls inside one agent (C3)"]),
    "C7_output_parsing": (
        "A response was produced but could not be interpreted or validated: "
        "malformed JSON, a schema violation, a missing key, or a wrong type.",
        ["JSON decoding of model output fails",
         "Pydantic or JSON-schema validation fails on the response",
         "A required key is absent or mistyped in structured output"],
        ["Arguments fail validation while being sent to a tool (C5)",
         "The response parses correctly but states the wrong answer (C4)"]),
    "C8_runtime_other": (
        "The failure occurred in runtime behaviour not covered above, after at "
        "least one successful call: orchestration bookkeeping, scheduling, "
        "logging, or teardown.",
        ["Framework bookkeeping raises after a successful call",
         "Cleanup or teardown fails at the end of a run",
         "The behaviour fits no earlier stage on this list"],
        ["The failure is attributable to a specific earlier stage, which takes "
         "precedence"]),
}

D_FILL = {
    "D1_blocking": (
        "Execution cannot continue: an unhandled exception, crash or hard stop, "
        "with no usable deliverable.",
        ["The run aborts with an exception",
         "The process exits or hangs until killed",
         "No output is produced at all"],
        ["The run completes but the deliverable is wrong (D2)",
         "The run completes with a workaround or reduced quality (D3)"]),
    "D2_incorrect_output": (
        "The run completes, but the deliverable is wrong or silently corrupted - "
        "the most expensive mode, because nothing signals it.",
        ["A wrong answer, plan or artefact is delivered as if correct",
         "Part of the task is silently skipped",
         "Output is corrupted but well formed"],
        ["An exception stops the run (D1)",
         "Quality is reduced but the output is usable with a workaround (D3)"]),
    "D3_degraded": (
        "The run completes with a loss of quality, a workaround, or partial "
        "output that remains usable.",
        ["A fallback path or manual workaround is required",
         "Output covers only part of the requested task",
         "The result is slower or noisier but correct"],
        ["Nothing usable is produced (D1)",
         "The delivered result is wrong rather than merely reduced (D2)"]),
    "D4_minor": (
        "Cosmetic or non-blocking: noisy logging, warnings, or formatting issues "
        "that do not change the result.",
        ["Warnings or deprecation notices with no functional effect",
         "Log noise or duplicated messages",
         "Formatting or typography defects in output"],
        ["The result or the availability of the run changes (D1, D2 or D3)"]),
}

E_FILL = {
    "E1_framework_runtime": (
        "The framework or runtime raised the failure itself, as an exception or "
        "a stop.",
        ["An exception is surfaced to the caller",
         "The framework logs an error and halts",
         "A guard in the runtime rejects the call"],
        ["The run finishes and a human notices the output is wrong (E3)"]),
    "E2_external_test": (
        "A test, evaluation harness or assertion caught it, including CI.",
        ["A unit or integration test fails",
         "An evaluation harness score drops below its threshold",
         "A CI assertion rejects the build"],
        ["The product runtime raised it while running for a user (E1)"]),
    "E3_human_observation": (
        "A person noticed it by inspecting output or behaviour, with no automated "
        "signal.",
        ["A user reports a wrong answer or a bad plan",
         "A reviewer spots the defect in the output",
         "The reporter found it while using the application"],
        ["An automated monitor or alert found it (E4)",
         "A test found it before release (E2)"]),
    "E4_production_monitoring": (
        "Logging, metrics or alerting detected it in operation.",
        ["An alert fired on an error rate or latency metric",
         "A dashboard or log review exposed the failure",
         "Tracing identified the failing step in production"],
        ["It was caught in a test rather than in operation (E2)"]),
    "E5_configuration_validation": (
        "A preflight or configuration check caught it during setup.",
        ["A start-up validation rejects the configuration",
         "A credential or connectivity check fails before any call",
         "A schema check on configuration refuses to start"],
        ["The error is raised later during a call (E1)"]),
}

D_ORDINAL = {"D1_blocking": 1, "D2_incorrect_output": 2, "D3_degraded": 3,
             "D4_minor": 4}


def main() -> None:
    spec = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    dims = spec["dimensions"]

    dims["A_failure_type"]["categories"]["A10_unknown"]["exclude"] = A_EXCLUDE_10

    for code, (inc, exc) in B_FILL.items():
        body = dims["B_cause_class"]["categories"][code]
        body["include"] = inc
        body["exclude"] = exc

    for code, (definition, inc, exc) in C_FILL.items():
        body = dims["C_lifecycle_stage"]["categories"][code]
        if isinstance(body, str):
            dims["C_lifecycle_stage"]["categories"][code] = {
                "label": body, "definition": definition,
                "include": inc, "exclude": exc}

    for code, (definition, inc, exc) in D_FILL.items():
        body = dims["D_severity"]["categories"][code]
        if isinstance(body, str):
            dims["D_severity"]["categories"][code] = {
                "label": body, "definition": definition,
                "ordinal": D_ORDINAL[code], "include": inc, "exclude": exc}

    for code, (definition, inc, exc) in E_FILL.items():
        body = dims["E_detection_point"]["categories"][code]
        if isinstance(body, str):
            dims["E_detection_point"]["categories"][code] = {
                "label": body, "definition": definition,
                "include": inc, "exclude": exc}

    meta = spec.setdefault("meta", {})
    meta["boundaries"] = ("every code carries definition, include and exclude; "
                          "dimension D is ordered, most severe first")

    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=88)
    PATH.write_text(HEADER + "\n" + body, encoding="utf-8")

    # report what changed
    n = sum(len(dims[d]["categories"]) for d in dims)
    complete = sum(1 for d in dims for c in dims[d]["categories"]
                   if isinstance(dims[d]["categories"][c], dict)
                   and all(dims[d]["categories"][c].get(k)
                           for k in ("definition", "include", "exclude")))
    print(f"codes: {n}, fully specified: {complete}")
    for d in dims:
        print(f"  {d}: {len(dims[d]['categories'])}")


if __name__ == "__main__":
    main()

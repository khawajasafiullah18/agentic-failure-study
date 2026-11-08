# Column schema

| Column | Type | Meaning |
|---|---|---|
| `record_id` | `string` | Stable hash of repository and issue number |
| `source_url` | `string` | Link to the original public report |
| `repository` | `string` | owner/name of the GitHub repository |
| `framework` | `string` | Agent orchestration framework under study |
| `issue_number` | `int64` | Issue number within the repository |
| `created_at` | `string` | ISO-8601 timestamp the report was filed |
| `year` | `int32` | Year the report was filed |
| `state` | `string` | Issue state at collection time |
| `state_reason` | `string` | Why the issue was closed, when given |
| `issue_labels` | `string` | Labels applied by the project, pipe separated |
| `comments` | `int32` | Number of comments on the report |
| `reactions` | `int32` | Reaction count at collection time |
| `body_chars` | `int32` | Length of the original report body |
| `title` | `string` | Reported title, quoted verbatim |
| `failure_type` | `string` | Dimension A code |
| `failure_type_label` | `string` | Human-readable dimension A label |
| `failure_type_confidence` | `float` | Labeller confidence for dimension A |
| `evidence_span` | `string` | Quoted span that produced the dimension A label |
| `cause_class` | `string` | Dimension B code |
| `cause_label` | `string` | Human-readable dimension B label |
| `cause_secondary` | `string` | Optional secondary cause code |
| `cause_confidence` | `float` | Labeller confidence for dimension B |
| `cause_evidence_grade` | `string` | demonstrated | supported | hypothesised | unknown |
| `lifecycle_stage` | `string` | Dimension C code |
| `severity` | `string` | Dimension D code, ordered rubric |
| `detection_point` | `string` | Dimension E code |
| `complexity_tier` | `int8` | Declared capabilities: 0-3 |
| `complexity_multi_agent` | `bool` | Report declares more than one agent role |
| `complexity_uses_tools` | `bool` | Report declares tool or retrieval use |
| `complexity_uses_memory` | `bool` | Report declares persistent state or memory |
| `matched_rules` | `string` | Rules that fired, semicolon separated (audit trail) |
| `taxonomy_version` | `string` | Codebook version applied to this row |

## Exemplars (`data/exemplars.parquet`)

| Column | Type | Meaning |
|---|---|---|
| `category` | `string` | Dimension A code the example demonstrates |
| `category_label` | `string` | Human-readable label |
| `rank_in_category` | `int32` | 1 is the primary example for the category |
| `framework` | `string` | Framework the failing system uses |
| `issue_number` | `int64` | Issue number within the repository |
| `url` | `string` | Link to the original report |
| `title` | `string` | Reported title, quoted verbatim |
| `evidence` | `string` | Quoted span that justifies the label |

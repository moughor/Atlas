# Atlas 2.x Common Evidence Model

## Contract

PR130–PR139 extend the evidence carried by the PR129 canonical `KnowledgeGraph`.
Specialized Java, dependency, call, control-flow, data-flow, security, and workspace
graphs remain authoritative in their domains. They publish traceable, source-free
facts; downstream features never rebuild repository relationships.

Every conclusion references immutable evidence records:

| Field | Meaning |
|---|---|
| `evidence_id` | Stable digest of producer, snapshot, subject, kind, and normalized detail |
| `kind` | `graph_edge`, `graph_node`, `semantic_fact`, `analysis_result`, or `repository_metadata` |
| `subject_id` | Canonical node, edge, finding, or report item |
| `producer` | Existing pass/service and schema version |
| `snapshot_id` | Source semantic snapshot |
| `source_refs` | Canonical and specialized-result IDs, never raw source |
| `scope` | Repository, project, package, type, member, dependency, or finding |
| `language` | Language or explicit `unknown` |
| `detail` | Normalized metadata needed to reproduce the conclusion |
| `limitations` | Unresolved identities, partial coverage, and open-world assumptions |

Records serialize by `(kind, subject_id, evidence_id)`; maps use sorted keys and sets
sorted arrays. Unknown compatible fields survive `from_dict()` in `extensions`.

## Evidence and citations

Edge evidence proves resolved relationships. Semantic evidence proves typed properties.
Analysis evidence references authoritative analyzer results such as taint or impact
paths. Repository evidence describes discovery, configuration, and build metadata.
Names, prose, paths, and LLM output are hints only and cannot establish facts.

An evidence index deduplicates records. AI citations trace:

`statement -> derived result -> evidence record -> producer result/canonical ID`.

Untraceable output cannot support production claims. Missing evidence means `unknown`,
never `false`. Negative evidence is valid only when an analyzer records an executed
closed-world check, scope, and coverage. Conflicts remain visible.

Older snapshots without evidence remain readable. Incremental analysis invalidates
evidence when referenced results, IDs, configuration, producer versions, or snapshot
lineage change.

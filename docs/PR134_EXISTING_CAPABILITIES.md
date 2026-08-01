# PR134 Existing Capabilities and Gap Analysis

## Scope and authority

PR134 implements Explain Anything as defined by the official roadmap,
`ROADMAP_DEPENDENCY_MATRIX.md`, and `PR134_DESIGN.md`. The specifications agree:
PR134 introduces the first canonical subject resolver and composes bounded
explanations from existing semantic snapshots, the PR129 graph, and traceable
producer findings. It does not perform semantic search, impact prediction,
refactoring, security analysis, or another repository analysis.

PR133 is optional enrichment. Repository and narrow-subject explanations must
continue to work truthfully when compatible PR130 through PR133 results are absent.

## Capability and gap matrix

| PR134 capability | Existing implementation | Reuse decision | Missing PR134 work |
| --- | --- | --- | --- |
| Canonical identities | PR129 `KnowledgeGraph` nodes and project-scoped symbol IDs | Reuse unchanged | Indexed, ambiguity-safe subject resolution |
| Graph queries | O(1) `get()` and indexed, sorted `incoming()` / `outgoing()` | Reuse direct adjacency; do not copy the graph | Bounded cycle-safe selection with exact omission counts |
| Repository explanation | PR133 deterministic report projector, selector, and renderer | Preserve byte-compatible default behavior | Attach structured PR134 metadata without replacing the report |
| Targeted explanation | PR114 `ExplainEngine`, CLI `--subject`, provider, and conversation memory | Preserve the public request/result prefix and provider-backed narrative | Replace the full-snapshot prompt with resolved, bounded structured context |
| Evidence | PR130 `EvidenceRecord` and `EvidenceIndex`; PR130–PR133 evidence indexes | Verify and cite existing records; derive only bounded PR134 citations | Explanation-level evidence closure and tamper checks |
| Confidence | PR130 `ConfidenceCalculator` and `ConfidenceResult` | Reuse without new thresholds or scores | Preserve upstream confidence and use exact/unavailable bases honestly |
| Repository facts | PR127 summary, PR128 architecture, PR130 patterns, PR131 reachability, PR132 risk, PR133 report | Consume compatible structured results only | Subject-scoped projections and explicit unavailable states |
| Source metadata | `semantic_context.symbols` contains simple names and workspace-relative paths keyed by canonical ID | Use only as an indexed resolution constraint | Reject absolute or unmatched paths from output and prompts |
| Token budgeting | PR133 deterministic estimator and bounded context-selection convention | Extend the established convention for the second real consumer | Explanation-specific whole-fact selection and truncation metadata |
| Snapshot persistence | ASS schema 1 and additive semantic-context fields | Read existing data; explanations remain ephemeral | Result lineage, graph digest, and snapshot reference |

## Supported subjects

The implementation scope follows `PR134_DESIGN.md`:

- repository and workspace;
- project;
- package and module;
- class/type and method;
- dependency;
- framework;
- build system and real build target;
- generic canonical symbol;
- an explicit canonical graph relationship.

Architecture, pattern, reachability, risk, and repository-report findings enrich a
resolved subject when traceable. They are not new primary subject kinds. A build
system is never relabeled as a build target; the normal pipeline currently emits no
real build-target nodes, so that capability is explicitly unavailable unless a
structured producer supplies one.

## Resolver extension

No canonical subject resolver currently exists. The PR129 graph's `find()` and
`by_kind()` scan every node and cannot represent ambiguity. The new resolver will
build one immutable in-memory index per snapshot and apply this order exactly:

1. canonical ID;
2. exact qualified name within supplied scope constraints;
3. one unique normalized name;
4. bounded deterministic candidates requiring disambiguation.

Kind, project, language, and workspace-relative path constrain matches. Resolution
does not use substrings, fuzzy similarity, class-name heuristics, LLM output, or the
future PR135 semantic-search engine. Duplicate qualified names, overloads, and
project/module name collisions are never resolved by choosing the first match.

Repository and workspace PR129 IDs contain the machine-specific root. They remain
internal canonical graph identities and are represented by safe public references in
serialized explanations and prompts; PR129 IDs themselves are not changed.

## Explanation extension

The current targeted path serializes the complete ASS into `atlas-grounded-v1` and
does not resolve or select the requested subject. PR134 will instead produce one
immutable structured explanation containing:

- request and resolution status;
- resolved subject or disambiguation candidates;
- bounded factual statements and relationships;
- producer IDs, evidence IDs, confidence, coverage/availability, and limitations;
- graph and snapshot lineage;
- exact included and omitted counts;
- deterministic context digest and token-selection metadata.

The provider, when configured, receives only this structured source-free explanation.
Its prose remains optional presentation and cannot replace or alter the structured
facts. Unknown, ambiguous, unsupported, and unavailable requests return explicit
structured states instead of speculative answers.

## Compatibility and regression risks

- **Default-report regression:** repository-default output must continue through the
  accepted PR133 renderer and remain provider-free.
- **Prompt size:** Maven and Quarkus snapshots are tens or hundreds of megabytes;
  full ASS serialization must be removed from targeted explanation.
- **Identity ambiguity:** duplicated names and overloads require disambiguation, not a
  best guess.
- **Path leakage:** repository/workspace graph IDs, symbol sources, dependency
  sources, diagnostics, and upstream source references can contain absolute paths.
  Serialized PR134 output recursively rejects them.
- **Incomplete graph evidence:** absent calls or composition remain unavailable and
  are never interpreted as negative evidence.
- **Malformed or old snapshots:** missing, future-schema, duplicate-ID, or dangling
  graph data degrades explicitly instead of crashing or creating a replacement graph.
- **High-degree subjects:** traversal and citations require hard bounds and exact
  omission counts.
- **Narrative invention:** prompts require citations and fact/interpretation
  separation; provider prose never changes structured availability or confidence.
- **Conversation compatibility:** existing memory ordering and snapshot references
  must remain valid.

## Inherited limitations deliberately unchanged

The approved PR130 implementation does not currently preserve unknown evidence fields
through an `extensions` member, and its no-role confidence outcome is represented by
the accepted `insufficient` contract. PR134 reuses that implementation exactly and
does not introduce a competing evidence or confidence model. Any future contract
alignment must be handled separately and compatibly.

## Explicitly out of scope

- natural-language intent parsing or fuzzy semantic search (PR135);
- impact or blast-radius prediction (PR136);
- refactoring, security, or chat engines (PR137–PR139);
- line-level source explanation, raw-source prompts, or automatic changes;
- graph mutation, another repository report, persistent caches, or parallelism;
- new call, control-flow, dependency, architecture, pattern, risk, or Git analyzers.

# PR136 Existing Capabilities

Status: pre-implementation audit recorded before PR136 production changes. This
document describes reusable behavior and known gaps; it does not claim that impact
prediction has been implemented.

## Baseline

PR136 starts from commit `cddfefc09ee7ae2ceeb908f167568797c02041d0`.
At inspection time the worktree was clean and `HEAD` matched `origin/main`.

## Capability audit

| Capability | Existing owner | Current guarantees | Reuse strategy | Missing PR136 work |
| --- | --- | --- | --- | --- |
| Subject resolution | PR134 `CanonicalSubjectResolver` | Resolves canonical IDs, qualified and normalized names, kinds, projects, packages, modules, and dependency subjects with deterministic ambiguity | Delegate identity and scope handling; add only impact-request validation | Convert resolution, ambiguity, and unavailable states into impact responses |
| Direct dependencies | PR129 `KnowledgeGraph`, dependency intelligence, and legacy dependency graphs | Traceable declared project, module-like, dependency-coordinate, framework, and supported import relationships when populated | Query canonical relations and adapt authoritative specialized dependency results to canonical IDs | Change-kind-aware impact categories, evidence paths, scope/version handling, and capability reporting |
| Reverse dependencies | PR129 bounded incoming adjacency and PR26 `ImpactAnalysisService` | Deterministic reverse traversal over relationships supplied by the caller | Reuse adjacency and the proven BFS shape; retain relation semantics and evidence | Bounded multi-relation traversal, deterministic predecessor selection, truncation, and partial coverage |
| Inheritance | PR129 canonical graph and authoritative Java/Python semantic producers | Resolved Java extends/implements and Python bases where targets are unique and internal | Traverse child-to-base evidence in reverse only for compatible change kinds | Impact-specific propagation, path confidence, and unsupported-language reporting |
| Overrides | PR129 canonical graph and Java semantic metadata | Conservative Java `@Override` mapping to a resolved ancestor with matching name and parameter signature | Reuse traceable canonical edges; do not reconstruct overrides | Signature/removal propagation and explicit generic, external, and unannotated limitations |
| Calls | Specialized `CallGraph`, PR131 optional call evidence, and Java workspace call-flow services | Authoritative only inside the supplied specialized result; canonical calls are not populated by the normal snapshot pipeline | Adapt compatible specialized endpoints to canonical IDs without copying them into another graph | Call capability/coverage, evidence validation, and caller impact; otherwise report not evaluated |
| Ownership and hierarchy | PR129 `ownership` and `member_of`; PR127 repository hierarchy | Source-free repository, workspace, project, module-like, package, type, and member containment where represented | Use for aggregation and scope, never as behavioral reachability or sibling fan-out | Relation-direction rules and partial module-identity reporting |
| Test linkage | PR131 reachability contracts and optional specialized call/reference evidence | Production/test roots and coverage can be represented; the normal pipeline lacks complete per-symbol test linkage | Reuse explicit test relations and authoritative references when supplied | Separate directly linked, structurally related, suggested, and unavailable tests |
| Public API | Java visibility/modifier metadata, PR131 external-API protections, and canonical ownership | Identifies some public/protected subjects and their repository scope; it does not prove external consumers or binary compatibility | Reuse only compatible structured visibility, signature, ownership, and diff facts | Conservative before/after API comparison and proven/potential/not-evaluated/unsupported states |
| Git changes | `git_diff`, history, and AI Git-context components | Structured repository change/history context exists when Git is available | Resolve changed subjects through PR134 and use Git only as optional prioritization evidence | Canonical joins, compatibility checks, lineage, coverage, and source-free projection |
| Risk context | PR132 `RiskAnalysisReport` | Deterministic hotspots, factors, evidence, confidence, coverage, producer version, and graph lineage | Read compatible findings without recalculating risk | Attach optional context and limitations without changing impact existence |
| Search enrichment | PR135 semantic search | Deterministic relevance and candidate ranking over source-free facts | Use only for broad wording, candidate selection, or weak suggestions | Keep relevance evidence separate from structural impact evidence |
| Reachability | PR131 `DeadCodeReport` and `ReachabilityAnalysisService` | Conservative roots, paths, protections, project coverage, and explicit unknown states | Consume compatible findings as contextual evidence; specialized graphs remain authoritative | Map relevant coverage without interpreting absence as no impact |
| Evidence and confidence | Shared PR130 `EvidenceIndex`, `EvidenceRecord`, and `ConfidenceCalculator` | Stable evidence IDs and deterministic confidence from roles, coverage, agreement, contradiction, and ambiguity | Extend the shared contracts with PR136 evidence roles | Evidence-backed impact paths, weakest-edge limits, coverage decay, and exact validation |
| Snapshots and lineage | `AtlasSemanticSnapshot`, existing producer/version and graph-digest conventions | Older snapshots and optional feature sections remain readable; derived features can validate lineage | Construct impact analysis from compatible source-free facts | Optional PR136 payload decision, exact round trip, invalidation, and explicit unavailable state |
| Persistence and caching | Existing snapshot stores and feature-local cache conventions | Feature data can be reconstructed and invalidated using snapshot lineage and producer fingerprints | Begin without a persistent impact cache; reuse existing lifecycle rules if measurement later justifies one | Bounded immutable in-memory indexes and documented invalidation inputs |
| Measurement | M2 `MeasurementSession` | Stable opt-in phase timing and counters without changing semantic output | Add only PR136-specific phases and counters | Measure resolution, adjacency, traversal, scoring, evidence, sorting, and serialization |
| CLI and public API | Unified Typer CLI, PR105 facade, and deterministic JSON conventions | Additive commands/services can load existing snapshots without an LLM | Preserve exit-code, rendering, and public-manifest conventions | Bounded `atlas impact` command and immutable snapshot-backed Python contracts |

## Production evidence support and limits

| Evidence | Production support | Direction and permitted use | Limitations |
| --- | --- | --- | --- |
| `depends_on` | Populated for declared workspace/project, dependency-coordinate, framework, and supported dependency facts | Consumer to provider; reverse traversal may identify potential dependents | Declaration does not prove runtime use; scope and unresolved version remain unknown when absent |
| `imports` | Populated from structured Python and TypeScript import metadata | Importer to resolved internal target; reverse traversal may identify importers | Java import metadata is not normally persisted; ambiguous and external targets are omitted |
| `inheritance` | Populated for resolved Java and Python relationships | Subtype to base; compatible base changes may propagate to incoming subtypes | External, ambiguous, or unsupported-language bases are absent, not negative evidence |
| `overrides` | Conservatively populated for Java | Overriding member to overridden member; compatible base API changes may propagate in reverse | Unannotated, generic-erasure, external, and ambiguous cases remain unknown |
| `calls` | Available only from compatible authoritative specialized results | Caller to callee; callee change may propagate to incoming callers | Canonical traversal requires the producer-bound `moughorai.call_graph.v1:calls` marker; missing calls mean call impact was not evaluated |
| `composition` | Not populated by a reliable production producer | No propagation | Typed field use does not establish lifecycle composition |
| `ownership` | Populated for repository/workspace/project/module-like containment | Container to child; use for aggregation and scope | Must not propagate from a child through its owner to unrelated siblings |
| `member_of` | Populated for resolved symbol membership | Member to owner; use for API/container aggregation | Membership alone is not behavioral impact |
| Test relations | Optional explicit or authoritative call/reference evidence | Exact test-to-subject evidence may support direct test impact | Same scope, names, search relevance, and Git co-change are prioritization only |
| API evidence | Partial structured visibility, signatures where retained, ownership, and explicit requested/diff facts | Supports public-surface context and conservative compatibility classification | Proven breaking change requires compatible before/after evidence; repository-local absence does not prove external safety |
| Git, risk, and search | Optional structured enrichment | May prioritize evidence-backed findings or propose candidates for explicit selection | Cannot create an impact path, dependency, breaking-change fact, or high-confidence direct finding |

Missing graph evidence is never evidence of no impact. Canonical `calls` and
`composition` enum values describe model capacity, not current producer coverage.
Names, package labels, lexical similarity, Git co-change, risk, and LLM output cannot
independently establish impact.

## Architecture decisions for PR136

- PR129 remains the only canonical repository graph and is not modified by PR136.
- PR134 remains the only canonical subject resolver. PR135 is optional enrichment,
  not an identity or impact dependency.
- Existing dependency, Java workspace, call, reachability, API, Git, and risk
  analyzers remain authoritative in their domains. PR136 adapts compatible results;
  it does not duplicate their analysis.
- Traversal is relation-aware and direction-aware. A generic reverse walk across all
  edges would incorrectly turn ownership and weak contextual relations into impact.
- Structural impact, search relevance, reachability, risk, and breaking compatibility
  remain separate concepts and separate response fields.
- Confidence uses the shared calculator. Path reliability cannot exceed its weakest
  edge, and incomplete coverage lowers confidence or produces `insufficient`.
- Impact score orders already supported findings; it does not manufacture evidence.
  Missing optional signals are excluded rather than treated as negative values.
- Module-level output must report partial coverage where Atlas represents a project-
  derived module rather than an independent build/source-set identity. The accepted
  IntelliJ module-identity limitation remains visible.
- No persistent cache is justified before PR136 construction and warm-query costs
  are measured. Any initial index is immutable, bounded, feature-local, and
  reconstructible from compatible snapshot facts.
- PR136 does not add PR137 refactoring recommendations or PR138 security detection.

## Missing work and intended extensions

PR136 still requires immutable request, path, finding, capability, score, and response
contracts; exact serialization; an impact-specific evidence taxonomy; deterministic
direct discovery and bounded transitive traversal; conservative API, test,
dependency, and module classifications; optional Git/risk/search enrichment; CLI and
public API entry points; source-free projection; M2 instrumentation; and focused,
adversarial, compatibility, performance, and benchmark validation.

The implementation must preserve explicit `available`, `partial`, `unavailable`,
`incompatible`, and `unsupported` states. A request-declared hypothetical signature
change may establish a scenario but cannot be labeled a proven breaking change
without structured before/after evidence.

No second graph, resolver, dependency analyzer, risk engine, evidence model,
confidence model, change-review engine, persistent global cache, embedding service,
or LLM dependency is required.

## Regression and compatibility risks

- Legacy PR26 and Java impact APIs have established DTOs and traversal behavior;
  PR136 must be additive rather than silently changing them.
- Older snapshots may lack PR129 relations, PR131 reachability, PR132 risk, PR134
  identity metadata, PR135 search, or Git context. Each missing or incompatible input
  must degrade one capability without failing the whole response.
- Edge direction differs by relation. Reversing `ownership` as if it were
  `depends_on` can create repository-wide false positives.
- Canonical calls are usually absent. Treating an empty incoming-call set as proof of
  no callers would under-report impact and external exposure.
- Public/protected APIs can have consumers outside the repository. No local consumer
  found is not a compatibility guarantee.
- Dependency declarations may be test-only, optional, inherited, unresolved, or
  non-runtime. Normalizing absent scope/version values would fabricate precision.
- Same names, packages, projects, search concepts, Git co-change, or risk rank can
  mislead ranking. None may become a structural edge.
- Multi-project duplicate names require canonical scope and deterministic ambiguity;
  the resolver must not choose by traversal or insertion order.
- Enterprise graphs require strict depth, visited-node, candidate, path, and output
  bounds with deterministic omitted counts.
- Paths, exception text, Git remotes, symbol metadata, and specialized results can
  contain private material. Only allowlisted source-free projections may enter PR136
  responses or snapshots.
- Snapshot and report ordering must not depend on graph insertion, hash iteration,
  worker completion, timestamps, or random identifiers.

# PR142 Existing Capabilities

Status: pre-implementation capability audit for the approved first PR142 slice.

## Roadmap authority

The official roadmap identifies PR142 as **Technical Debt Engine**:

> Rank technical debt by engineering impact and reuse PR132 complexity and risk
> evidence.

This wording does not authorize a new complexity analyzer, risk formula, graph,
impact engine, or generic inference framework. The first independently useful and
evidence-supported slice is limited to dependency-cycle seams already verified by
PR137. PR143, the exact next roadmap item, is **Architectural Drift**; intended
architecture and drift remain outside PR142.

## Existing authoritative capabilities

| Responsibility | Existing owner | Reusable behavior | PR142 boundary |
| --- | --- | --- | --- |
| Semantic archive | PR111 `AtlasSemanticSnapshot` and `SemanticSnapshotStore` | Checksum, content-derived snapshot identity, analyzer identity, and deterministic semantic context | PR142 consumes one verified snapshot and adds no snapshot format or store |
| Repository summary | PR127 `RepositorySummary` | Project inventory, module hierarchy, languages, build systems, and complete file-size metadata | Raw paths and counts do not establish debt; size is consumed only through PR132 |
| Architecture candidates | PR128 `ArchitectureReport` | Source-free dependency directions and reported cycles | Architecture-name findings are not debt evidence; reported cycles require PR137 revalidation |
| Canonical graph | PR129 `KnowledgeGraph` | Canonical subjects, represented relationships, stable digest, and indexed adjacency | Supported relation enum values do not prove population; PR142 does not create or traverse a second graph |
| Evidence and confidence | PR130 `EvidenceRecord`, `EvidenceIndex`, and `ConfidenceCalculator` | Deterministic IDs, evidence roles, coverage, limitations, and confidence tiers | PR142 reuses these contracts and cannot alter upstream confidence |
| Reachability | PR131 `DeadCodeReport` | Conservative reachability states and explicit coverage | Deferred from the cycle-only slice because missing call evidence prevents a uniformly comparable impact ranking |
| Risk and complexity context | PR132 `RiskAnalysisReport` | Exact-subject risk factors, independent confidence, capability states, and optional structured complexity | Risk is context, not proof of debt. Complexity remains unavailable unless the compatible PR132 report contains a structured observation |
| Repository report | PR133 `RepositoryReport` | Bounded presentation of PR128 cycles and PR131 candidates | It explicitly is not PR142. PR142 consumes primary typed results rather than report prose |
| Subject identity | PR134 `CanonicalSubjectResolver` | Source-free canonical subject resolution and graph restoration | No second resolver or name-based fallback |
| Semantic search | PR135 search | Deterministic discovery over structured facts | Search rank cannot establish debt, impact, or identity and is not used in the first slice |
| Engineering impact | PR136 `ImpactPredictionService` | Bounded, relation-aware represented impact with explicit unavailable and partial states | Impact is repository-local represented exposure, not runtime execution or a total blast radius |
| Verified cycle seams | PR137 `RefactoringAdvisorService` | Revalidates every reported cycle step against authoritative PR129 edge evidence and emits source-free cycle evidence | This is the only first-slice debt candidate source; PR142 does not rediscover cycles or refactoring advice |
| Security | PR138 security intelligence | Evidence-backed current-state security findings | Security findings are not automatically technical debt and are not consumed |
| Chat and change review | PR139 and PR140 | Grounded interaction and deterministic Git-aware review | Provider output and diff review do not establish repository debt |
| Repository evolution | PR141 `RepositoryEvolutionService` | Exact bounded canonical graph differences between two compatible snapshots | Evolution is not used by PR142 v1; a graph delta does not establish debt growth, causality, or intent |

## Persisted semantic projections

The relevant source-free semantic context already contains:

- `semantic_graph`: PR129 schema-1 canonical graph;
- `architecture`: PR128 schema-1 architecture projection;
- `risk_analysis`: PR132 producer `atlas-pr132/1`, schema 1;
- `repository_report`: PR133 presentation projection.

PR137 and PR136 responses are request-local and reconstructible from the verified
snapshot. PR142 invokes those existing services rather than persisting their complete
responses in another snapshot section.

The PR128 architecture model has no shared evidence index or snapshot lineage. A raw
`dependency_cycles` entry is therefore not sufficient by itself. PR137 is the
authoritative adapter for this slice because it resolves every cycle member through
PR134, confirms every step against PR129, rejects incomplete evidence, and emits
canonical shared evidence under the active snapshot lineage.

## PR132 evidence available in normal production

PR132 can normally provide:

- positive represented fan-in and fan-out;
- complete project inventory bytes;
- bounded Git change frequency when Git evidence is available;
- bounded change-author concentration when Git evidence is available.

The following remain explicitly unavailable without another structured producer:

- cyclomatic or cognitive complexity;
- resolved production-symbol-to-test density;
- symbol-level size;
- call-specific degree when authoritative calls are unavailable;
- historical risk trend without a compatible prior PR132 report.

PR142 does not replace an unavailable signal with graph degree, project size,
diagnostics, names, report text, Git co-change, or LLM output.

## Selected first slice

The approved first slice ranks only PR137-verified dependency-cycle seams. For each
retained seam it:

1. preserves the verified PR137 cycle evidence and limitations;
2. consumes PR136 represented impact for the exact canonical seam subjects;
3. attaches compatible exact-subject PR132 risk and complexity context when present;
4. keeps debt evidence, impact, risk, complexity, and confidence as distinct fields;
5. emits an ordinal deterministic rank without inventing a composite score;
6. retains a verified seam as explicitly **unranked** when comparable impact evidence
   is unavailable or insufficient.

Equivalent PR137 observations that share the same directed canonical seam are
merged before impact evaluation. Their evidence and advice IDs remain traceable,
but they produce one debt item and never increase rank. Response counts distinguish
upstream observations, unique evaluated seams, collapsed equivalents, unevaluated
observations, and output omissions.

Unranked means that Atlas has verified the cycle seam but lacks sufficient comparable
engineering-impact evidence. It does not mean low impact, no impact, or no debt.

## Rejected alternatives

- Treat every PR132 hotspot as technical debt. Risk is an investigation indicator,
  not evidence that debt exists.
- Use PR128 architecture classifications, names, packages, or directory layout as
  debt evidence.
- Implement another cycle detector, graph walk, resolver, impact analysis, evidence
  model, confidence model, persistence layer, or cache.
- Recompute PR132 risk or complexity with a PR142 formula.
- Convert missing complexity, calls, tests, ownership, or impact into zero.
- Treat parser diagnostics, analyzer failures, recovery journals, or Atlas performance
  measurements as repository debt.
- Infer security debt from PR138 findings.
- Infer debt growth from PR141 node or relation changes.
- Include PR131 dead-code candidates before a comparable, evidence-preserving impact
  integration is demonstrated.
- Infer architectural drift, intended boundaries, migration safety, runtime behavior,
  ownership, API guarantees, developer intent, or remediation safety.

## Compatibility and lifecycle

The first slice is ephemeral and snapshot-backed. It adds no semantic snapshot key,
history table, recovery field, durable index, persistent cache, or conversation
state. It does not alter the frozen public v1 facade. Any additive internal or CLI
surface remains outside that legacy compatibility contract until an explicit public
API decision is made.

Older schema-1 snapshots remain readable. Missing or incompatible PR128, PR129,
PR132, PR136, or PR137 capability yields explicit `unavailable`, `insufficient`, or
`incompatible` state. It never yields an empty success claim such as “no technical
debt.”

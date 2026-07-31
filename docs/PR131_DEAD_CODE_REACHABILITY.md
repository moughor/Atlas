# PR131 Dead Code and Reachability Analysis

## Architecture

`ReachabilityAnalysisService` consumes the PR129 `KnowledgeGraph`. It builds bounded
adjacency indexes over call edges that already exist in the canonical graph and over
optional `moughorai.call_graph.CallGraph` results. It does not add edges to either
graph and does not create another call graph or CFG.

The service performs deterministic multi-source traversal once for production roots
and once for test roots. Reaching a member may establish that its owning type is
reachable; owning a member never establishes that the member is reachable. Inheritance,
typed usage, project dependencies, and ownership are not treated as calls.

## Report model

The additive snapshot key is `semantic_context.reachability`. Schema version `1` and
producer `atlas-pr131/1` publish structured roots, bounded paths, per-symbol states,
production/test flags, project coverage, capabilities, confidence, evidence IDs,
lineage, limitations, and statistics.

`DeadCodeReport.from_dict(report.to_dict()).to_dict()` is exactly idempotent. Unknown
schema versions fail explicitly. Older snapshots without `reachability` remain valid
and mean that the capability is unavailable, not that the repository has no dead
code.

Snapshot publication uses deterministic `grouped-findings-v1` serialization. Findings
with identical state, scope, confidence, evidence, and limitations share one record
containing sorted canonical subject IDs. Loading expands the groups back into the exact
per-symbol model, and grouped round trips are also exact. This avoids duplicating
project coverage evidence and limitations for thousands of `unknown` symbols.

## Conservative classification

PR131 implements `reachable`, `reachable_test_only`, `externally_reachable`,
`framework_managed`, `reflection_discovered`, `service_loader_discovered`,
`generated_or_annotation_managed`, `conditionally_reachable`, `unused`,
`likely_dead`, `unreachable`, and `unknown`.

`likely_dead` requires complete roots, complete authoritative calls, an explicit
closed-world scope, no production/test path, no public/protected protection, no
external/framework/reflection/Service Loader/generated protection, and shared PR130
confidence of at least `0.8`.

Missing calls produce `unknown`; partial calls can produce only `unused`. Public or
protected visibility without publication evidence produces `unused` or `unknown`,
never a dead-code candidate. Only `likely_dead` and bounded CFG-backed `unreachable`
findings appear in the dead-code candidate set.

## Evidence support

Normal production publication currently supports:

- canonical identity, ownership, and call edges when actually populated;
- Java `main` roots from parsed method modifiers and signatures;
- Java visibility, entry-point status, and annotations already produced by
  `JavaSymbolIndex`;
- supported framework annotations paired with project-local framework evidence;
- supported generated/annotation-managed contracts;
- optional in-memory call graphs attached by an analyzer.

Structured adapters support authoritative external/publication contracts, reflection,
Service Loader, framework lifecycle, generated linkage, source classification,
closed-world declarations, and CFG-unreachable results when supplied.

The normal pipeline does not currently publish complete calls, resolved reflection,
Service Loader descriptors, per-symbol generated/test roles, module publication
policy, or method-to-CFG associations. Those capabilities remain `unavailable` or
`partial`; PR131 does not reconstruct them from names, packages, paths, or LLM output.

## Confidence, cache, and performance

PR131 reuses PR130 `EvidenceRecord`, `EvidenceIndex`, `EvidenceRole`, and
`ConfidenceCalculator`. Evidence is source-free and no LLM participates in
classification or scoring.

The bounded feature-local cache fingerprints the graph, structured symbol metadata,
repository evidence, call reports, capability inputs, failures, producer/schema, and
configuration. Traversal is `O(V + E)`, visits each accepted relation once per
production/test scope, enumerates no all-pairs paths, and reports deterministic
partial coverage when configured bounds are reached.

## AI presentation

Default repository `atlas ai explain` context receives aggregate counts, compact
project coverage, a bounded representative set, and top limitations. It excludes
evidence records, full paths, large symbol lists, and raw source. The prompt forbids
converting `unknown` or `unused` into dead code or claiming code is safe to delete.
Targeted subject explanations retain the existing detailed semantic-context path.

## Compatibility and deliberate limitations

- The PR129 graph is never modified.
- PR130 confidence, evidence, and pattern output remain compatible.
- Existing CFG and call-graph APIs remain authoritative.
- Workspace execution still isolates project failures. The existing rule that a
  failed workspace run does not replace `latest.ass` is preserved; direct reports can
  represent failed scopes for future partial-publication consumers.
- Automatic deletion, runtime tracing, dynamic reflection expansion, Service Loader
  parsing, new CFG/call producers, and PR132 risk scoring are intentionally deferred.

# PR130 Existing Capabilities and Extension Record

## Baseline

PR130 is implemented on documentation baseline `f848850`. The last functional
repository-graph PR is PR129 (`aec84d0`).

## Existing components reused

- PR129 `KnowledgeGraph` is the only canonical repository graph.
- `KnowledgeGraphBuilder` and `KnowledgeGraph.from_dict()` provide canonical,
  deterministic graph publication and recovery.
- `JavaArchitectureGraph` remains authoritative for resolved Java inheritance,
  field, parameter, and method-return type relationships.
- `CallGraph` remains authoritative for resolved calls and constructor-call kinds
  when a caller supplies that optional analysis.
- `GlobalSymbol` ownership, inheritance, and override metadata continues to provide
  canonical symbol identity and relationships.
- `SemanticContextCollector`, `WorkspaceContextBuilder`, and
  `SemanticSnapshotStore` remain the normal source-free publication pipeline.
- Existing workspace persistence remains authoritative for recovered
  `SemanticDocument` values.

No existing graph, analyzer, parser, or semantic pass is replaced.

## Capability gaps before PR130

The baseline had no common evidence index, no implementation of the approved common
confidence formula, no design-pattern result model, and no design-pattern detection
service or snapshot section.

Canonical `calls` and `composition` relations are supported by the PR129 model but are
not populated by the normal production pipeline. The Java architecture artifact was
produced during analysis but discarded by persisted analysis-result encoding and was
not consumed during semantic-context collection.

## Extensions introduced by PR130

- A minimal common evidence record/index implementation used by PR130 findings.
- A deterministic confidence calculator implementing the approved evidence,
  coverage, agreement, contradiction, and ambiguity formula.
- Pattern findings, participants, capability availability, deterministic
  serialization, producer version, and input lineage.
- A bounded fingerprint cache local to `PatternDetectionService`.
- Reuse of Java architecture artifacts during normal semantic-context collection.
- Backward-compatible persistence of the optional Java architecture artifact.
- Source-free `design_patterns` publication in semantic snapshots.

## Production evidence support

Populated by the normal Java analysis path:

- Strategy: resolved inheritance plus typed client use of the abstraction.
- Builder: multiple resolved self-return types plus a distinct resolved product
  return type.

Available when existing optional call-graph or canonical call evidence is supplied:

- Factory;
- Adapter;
- Decorator;
- Command;
- Template Method.

Intentionally reported as `insufficient` with current producers:

- Observer: registration/subscription evidence is unavailable.
- Composite: collection composition evidence is unavailable.
- Chain of Responsibility: conditional forwarding evidence is unavailable.
- State: state-transition assignment/data-flow evidence is unavailable.

These limitations are not inferred from names and do not become negative findings.

## Regression risks and mitigations

- Multi-project symbol collisions: specialized facts resolve through project-scoped
  canonical qualified names; ambiguous matches are ignored.
- False positive fluent APIs: Builder findings include an explicit limitation and
  medium evidence-derived confidence.
- Snapshot growth: only evidence referenced by emitted findings is serialized.
- Recovery differences: Java architecture artifacts now round-trip through the
  existing additive persisted-document schema.
- Nondeterminism: all inputs, findings, evidence records, and capability entries use
  stable ordering and exact serialization tests.

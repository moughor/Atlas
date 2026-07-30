# PR129 Existing-Capability Assessment

## Already present

Atlas already has a queryable `KnowledgeGraph`, a symbol-level
`DependencyGraph`, Java-specific knowledge and architecture graphs, and the
source-free cross-language `semantic_graph` published by PR125. PR127 adds
repository projects, module hierarchy, build systems, frameworks, entry points,
and declared dependencies.

## Reused

PR129 extends `KnowledgeKind`, `KnowledgeRelation`, `KnowledgeGraph`, and
`KnowledgeGraphBuilder`. Snapshot publication continues through
`WorkspaceContextBuilder`; symbol identities, repository summary, dependency
intelligence, and specialized Java graphs remain compatible. The Java language
frontend now reuses `JavaArchitectureService` to persist resolved inheritance
and verified override facts in normal global-symbol metadata.

## Missing before PR129

The published graph represented only cross-language symbols, ownership, and
resolvable imports. Repository, workspace, project, module, external
dependency, framework, and build-system facts were separate JSON collections.
The published graph could not be restored into the existing query API.

## Extension

`KnowledgeGraphBuilder.build_context()` composes existing facts into one
deterministic graph. `KnowledgeGraph.to_dict()` preserves PR125 fields and
`KnowledgeGraph.from_dict()` restores the same queryable relationships.
The original `build(symbols, dependencies)` contract remains supported.
Dependency identity includes ecosystem, name, version, and scope so variants
are not silently merged.

## Regression risks and controls

- Stable snapshot fields could change: `id`, `kind`, `qualified_name`,
  `project_id`, and `language` remain present.
- New nodes could create architecture false positives: PR128 only searches
  package and type nodes.
- Relationship inference could become speculative: PR129 only converts
  recorded semantic edges and structured PR127/PR126 facts.
- Ordering could vary: node, edge, metadata, and evidence serialization is
  normalized and tested for exact reproducibility.
- Graph consolidation could replace specialized APIs: Java, call, dependency,
  persistence, and security graphs remain available and are not rewritten.

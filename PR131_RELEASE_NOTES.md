# PR131 Release Notes

PR131 adds deterministic dead-code and reachability analysis over the unchanged PR129
canonical `KnowledgeGraph` and optional authoritative `CallGraph` evidence.

The new `moughorai.reachability` package separates immutable models, bounded
production/test traversal, conservative classification, shared PR130 confidence, and
pipeline orchestration. It publishes roots, paths, symbol states, capability/coverage
status, evidence IDs, lineage, limitations, and statistics under the additive
`semantic_context.reachability` key.

Missing calls yield `unknown`; partial calls can yield only `unused`. A `likely_dead`
candidate requires complete calls and roots, an explicit closed-world scope, no live
path or structural protection, and confidence of at least 0.8. Public/protected,
external, framework, reflection, Service Loader, generated, annotation-managed, and
test-only symbols are protected conservatively.

Java visibility, annotations, and structurally verified `main` entry points now
survive the existing global-symbol persistence path. Optional call graphs attached to
semantic documents are consumed in memory without copying their edges into another
graph.

Snapshots use exact deterministic grouped-finding serialization to avoid repeating
project evidence for thousands of unknown subjects. Default repository explanations
receive only aggregate coverage, bounded representative findings, and limitations;
raw source, evidence records, paths, and large symbol lists remain excluded.

PR131 adds no deletion, refactoring, risk/hotspot scoring, runtime tracing, new call
graph/CFG producer, or other PR132+ behavior.

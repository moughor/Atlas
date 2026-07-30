# PR128 Existing-Capability Assessment

## Already present

Atlas already publishes a source-free repository summary and cross-language
semantic graph. `java_architecture` provides language-specific nodes, edges,
resolution evidence, and query APIs. Workspace snapshots are the established
publication boundary.

## Reused

PR128 consumes `repository_summary` and `semantic_graph` from the existing
context and optionally accepts `JavaArchitectureGraph` for Java-specific
relationship detail. It does not alter the analyzer registry or introduce
another graph representation.

## Missing before PR128

No repository-level service recognized layered, modular-monolith,
microservices, hexagonal, clean, CQRS, event-driven, or plugin architectures.
There was no unified report for project dependency directions, cycles, bounded
contexts, ports/adapters, or infrastructure layers.

## Extension

`ArchitectureDetectionService` adds independently replaceable deterministic
pattern detectors over existing facts. Every finding has a confidence and at
least one traceable evidence record.

## Regression risks and controls

- Naming evidence can create false positives; findings expose confidence and
  exact evidence instead of claiming certainty.
- Graph traversal could become non-deterministic; nodes, edges, evidence, and
  cycles are normalized and sorted.
- A new graph could conflict with PR129; PR128 consumes the published graph and
  explicitly defers graph unification.
- Snapshot compatibility could regress; architecture data is additive.

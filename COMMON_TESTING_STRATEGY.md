# Atlas 2.x Common Testing Strategy

Every PR130–PR139 implementation requires:

1. Unit tests for models, queries, scoring, ordering, round-trip, and invalidation.
2. Production-path integration tests using normal analysis and snapshot publication.
3. Backward-compatibility tests for existing APIs and specialized analyzers.
4. Source-free prompt tests.
5. Exact round-trip tests for every new snapshot field.

Golden fixtures include minimal positive evidence and nearest negatives. Adversarial
fixtures cover suggestive names, unresolved/duplicate symbols, overloads, generated
code, reflection, frameworks, partial languages, cycles, contradictory evidence, and
shuffled/concurrent input. Missing evidence must remain unknown.

Atlas self-analysis detects bootstrap regressions. JUnit validates large multi-project
Java behavior using the accepted statement: “JUnit workspace validated successfully:
41 discovered projects, including the root `junit-team` aggregator.” Mixed-language
fixtures verify explicit limitations.

Benchmarks cover cold/warm/incremental runs; 10k, 100k, and 1M-node graphs; high-degree
nodes; long chains; and bounded AI context. Record median/p95 time, peak RSS, cache
hits, snapshot bytes, feature bytes, and node/edge counts.

AI tests use a recording provider and fixed token estimator to verify selection,
citations, confidence language, truncation, memory boundaries, and unsupported
negative claims. Run focused tests during implementation and the full suite once for
delivery. Record exact commands, outputs, and warnings; never claim unexecuted tests.

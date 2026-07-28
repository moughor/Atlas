# PR52 — Declarative Taint Policy Engine

PR52 adds a deterministic policy layer above the PR51 interprocedural data-flow engine.

## Capabilities

- Exact, prefix, suffix, and substring symbol matching.
- Declarative source, sink, and sanitizer definitions.
- Stable priority ordering and duplicate-rule validation.
- Sanitizer-aware suppression.
- Deterministic conversion of flow paths into `SecurityFinding` objects.
- Policy metadata, source/sink evidence, and PR51 trace preservation.
- Aggregate `SecurityReport` generation.
- Built-in SQL injection, command injection, and path traversal policies.

The engine is offline and provider-neutral. It consumes `FlowPath` values and does not alter PR51 graph traversal.

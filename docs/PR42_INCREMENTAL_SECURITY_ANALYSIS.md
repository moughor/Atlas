# PR42 — Incremental Security Analysis and Persistent Cache

PR42 adds content-addressed incremental execution to the Java security frontend.

## Capabilities

- SHA-256 source fingerprints
- per-file cached findings and warnings
- deterministic JSON cache persistence
- analyzer-version cache invalidation
- changed, added, removed, reused, and invalidated file tracking
- Java type dependency extraction
- transitive dependent invalidation
- safe removal of findings for deleted files
- deterministic merged reports and statistics
- cache hit metrics
- forced full rebuild support

The scanner complements the existing symbol-level incremental planner. The older planner computes impacted symbols and files; PR42 persists concrete Java security results and reuses them when file content and dependencies remain valid.

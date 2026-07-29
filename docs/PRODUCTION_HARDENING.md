# Production hardening checkpoint

This checkpoint resolves the remaining actionable items from the independent
PR106 production review without adding product features.

- `IncrementalStateStore` now supports strict, versioned round-trip loading and
  uses unique fsynced temporary files for saves.
- `GlobalSymbolSnapshot` retains detached immutable indexes for constant-time
  identifier, qualified-name, simple-name, kind, and source lookups.
- Public single-shot semantic attachment helpers explicitly direct bulk callers
  to the corresponding pass APIs.
- Expression traversal uses semantic node keys instead of object identities.
- The Java frontend result is named `JavaAnalysisResult`; `SemanticDocument`
  remains an identity-preserving compatibility alias.
- Production modules use explicit imports instead of wildcard imports.
- Project scanning and indexing continue to reject file symlinks and do not
  follow directory symlinks by default.

`MemoryScorer` remains as a public compatibility specialization used by
`MemoryRetriever`. The previously reported backup and unused AST visitor files
were already absent.

## Verification

Baseline at commit `06f8ec3`:

```text
3323 passed in 7.01s
```

Final focused result:

```text
23 passed, 1 skipped in 0.31s
```

Final complete suite:

```text
3331 passed, 1 skipped in 7.12s
```

The skipped test requires file-symlink creation, which was unavailable in the
Windows test environment. It is reported as skipped rather than passed.

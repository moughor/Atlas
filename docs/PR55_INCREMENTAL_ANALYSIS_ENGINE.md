# PR55 — Incremental Analysis Engine

PR55 extends the existing `moughorai.incremental_analysis` package with deterministic content fingerprints, a persistent result cache, dependency-aware invalidation, cache statistics, corruption recovery, and resumable incremental execution.

## Design goals

- Re-analyze only files whose content changed or whose dependencies changed.
- Never rely on modification timestamps for correctness.
- Preserve deterministic ordering and serialization.
- Keep the PR18 planner and state-store APIs compatible.
- Recover safely from missing, corrupt, or incompatible cache files.
- Support concurrent cache readers and atomic cache persistence.

## Main APIs

### `FingerprintService`

Produces SHA-256 `FileFingerprint` values from bytes or files. Project scans are returned in stable case-insensitive path order.

### `IncrementalCache`

Stores JSON-compatible analysis results by logical file key and fingerprint. Entries can record dependencies, allowing direct or transitive invalidation. Cache files use schema version 1 and are written atomically.

### `IncrementalAnalysisEngine`

Compares previous and current fingerprints, classifies added/modified/removed/unchanged files, propagates invalidation through a dependency map, reuses valid cached results, and invokes the supplied analyzer only when required.

## Recovery

`IncrementalCache.load(path, recover=True)` returns an empty cache when the file is corrupt or uses an unsupported schema. With recovery disabled, the same condition raises `CacheFormatError`.

## Determinism

Paths, cache entries, dependencies, invalidation output, and JSON keys are sorted. Persisting equivalent caches therefore produces byte-identical JSON.

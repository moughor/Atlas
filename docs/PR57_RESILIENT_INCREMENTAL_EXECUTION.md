# PR57 — Resilient Incremental Execution

PR57 adds retryable and checkpointed execution above the deterministic parallel scheduler introduced in PR56.

## Capabilities

- configurable retry attempts and exception classes;
- deterministic per-file attempt records;
- atomic JSON checkpoints containing successful results;
- resume after interruption without re-running matching fingerprints;
- automatic exclusion of changed fingerprints;
- pruning of removed files;
- corruption detection with optional recovery;
- dependency cancellation and fail-fast compatibility;
- separate reporting of cache reuse and checkpoint resume.

Existing sequential and parallel APIs are unchanged. Use `ResilientParallelScheduler` only when retry or durable resume behavior is required.

# PR102 — Global Symbol Concurrency

`GlobalSymbolDatabase` is safe to share across PR73 workspace worker threads.
Every public lookup or mutation is linearizable under one reentrant lock.
Existing method signatures and deterministic result ordering are unchanged.

Use `add_many()` when publishing a related group of symbols. The complete
batch is validated before any index changes, so duplicate identifiers or
qualified names leave the database unchanged.

Call `snapshot()` when a consumer needs a stable view across several queries.
`GlobalSymbolSnapshot` is detached, immutable, and records the database
version from the same read transaction. Later additions and source removals do
not affect it.

The ownership contract is:

- single lookups and mutations may be called concurrently;
- compound reads use a snapshot when consistency across calls matters;
- external code must not depend on internal index identity;
- persistence obtains a stable tuple through the existing `symbols` property.

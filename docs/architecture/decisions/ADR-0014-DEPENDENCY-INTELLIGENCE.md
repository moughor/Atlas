# ADR-0014 Dependency Intelligence

## Status

Accepted

## Decision

Atlas uses one immutable `DeclaredDependency` model across supported manifest
formats. Discovery is file-based and parsing is non-executing. Results flow as
a semantic document artifact, survive recovery encoding, and are normalized
into semantic snapshots.

## Consequences

Consumers no longer need ecosystem-specific parsing. Declared constraints are
reported verbatim; PR126 does not resolve lockfiles, contact registries, or
claim which version is installed.

Optional versions remain `None` when they are unspecified or inherited. Production
consumers use `DeclaredDependency.deterministic_sort_key()` for ordering, which
normalizes the optional value only inside the comparison key and never changes the
stored semantic value.

# ADR-0013 Cross-Language Semantic Graph

## Status

Accepted

## Decision

Project-scoped global symbols are the common identity layer for Java, Python,
and TypeScript. Snapshot generation derives one deterministic JSON graph from
those identities. Language frontends remain independent behind the PR124
registry.

Graph edges currently express symbol ownership and statically resolvable
imports. Missing or ambiguous targets do not create speculative edges.

## Consequences

AI consumers can traverse multiple languages without parsing source. The graph
is additive to schema version 1 and preserves all existing context fields.

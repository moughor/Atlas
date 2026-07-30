# ADR-0007 Python Semantic Analyzer

Status

Implemented

Date

2026-07-30

---

## Context

Python repositories completed successfully but exposed no declarations to AI
services because production semantic extraction was Java-only.

## Decision

Use Python's standard-library `ast` parser as the authoritative syntax source.
Map declarations into the existing language-neutral `GlobalSymbol`,
`TypeTable`, `Diagnostic`, and `SemanticDocument` contracts.

PR122 extends the current project analyzer directly. Registration and
third-party language selection remain the responsibility of PR123.

## Alternatives Considered

- Regex parsing was rejected because Python nesting and annotations require a
  grammar-aware parser.
- A third-party CST dependency was rejected because PR122 does not perform
  formatting-preserving rewrites.
- Implementing the registry now was rejected because that would merge PR123.

## Consequences

- Python repositories produce rich deterministic AI context.
- No new runtime dependency is required.
- AST nodes remain in memory only; persisted data contains semantic facts.
- Python invocation remains in the project analyzer until PR123.

## Related PRs

PR121, PR122, PR123

## Related ADRs

ADR-0001, ADR-0002

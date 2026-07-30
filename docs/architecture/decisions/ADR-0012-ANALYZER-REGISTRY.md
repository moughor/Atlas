# ADR-0012 Analyzer Registry

## Status

Accepted

## Decision

Language frontends implement `LanguageAnalyzer` and register by stable language
name and normalized file extension. `AnalyzerRegistry` groups files, invokes
matching analyzers in deterministic language order, and merges their
language-neutral semantic documents.

Java and Python are built in. Other languages are plugins using the same
contract. Unknown extensions remain ignored instead of producing unverified
semantics.

## Compatibility

`SemanticProjectAnalyzer` remains a facade and workspace report metadata keeps
its pre-PR124 shape.

## Consequences

Language selection is extensible without changing the workspace orchestrator.
Extension ownership is unique and registry mutation is synchronized.

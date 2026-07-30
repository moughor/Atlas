# PR124 — Analyzer Registry

Atlas routes files through `AnalyzerRegistry` instead of hard-coding language
selection in the workspace analyzer. Java and Python remain built in. Language
plugins register a stable language name, file extensions, and an
`analyze(project, paths, dependencies)` implementation.

Registrations and routing are deterministic. Duplicate language names or
extension ownership are rejected unless explicitly replaced. Registry mutation
and lookup are synchronized for concurrent workspace execution.

Kotlin, JavaScript, TypeScript, Rust, and Go frontends use the same contract.
PR124 introduces their plugin boundary; it does not emit placeholder semantics
when a frontend has not been installed.

`SemanticProjectAnalyzer` remains a backward-compatible facade configured with
the built-in Java and Python analyzers.

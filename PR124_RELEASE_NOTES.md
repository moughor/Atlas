# PR124 Release Notes

PR124 introduces `AnalyzerRegistry`, a synchronized and deterministic language
frontend registry. Java and Python are built in; Kotlin, JavaScript, TypeScript,
Rust, Go, and third-party frontends can register through the same protocol.

The CLI now uses the registry. `SemanticProjectAnalyzer` remains compatible.
Unknown extensions are ignored and stable workspace report metadata is
unchanged.

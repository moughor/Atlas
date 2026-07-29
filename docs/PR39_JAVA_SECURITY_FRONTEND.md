# PR39 — Java Security Frontend

PR39 connects the language-neutral security engine from PR38 to Java source and Spring Boot configuration files.

## Capabilities

- deterministic parsing of security-relevant Java assignments and invocations
- servlet/environment source discovery
- sanitizer recognition and taint propagation through concatenation
- Java API sink normalization for SQL, commands, paths, SSRF, deserialization, reflection and XML
- multiline statement and nested-call support
- hardcoded credential detection from Java variable declarations
- `.properties`, `.yml`, and `.yaml` configuration parsing
- directory-level project scanning with preserved source locations
- merged JSON and SARIF-compatible security reports
- deterministic rule summaries and optional unsupported-statement warnings

The frontend is deliberately a focused security adapter, not a replacement for a complete Java compiler. It produces the PR38 `SecurityProgram` intermediate representation so future AST-based frontends can use the same analysis engine.

# PR38 — Security Analysis Engine

PR38 adds a deterministic, language-neutral security analysis layer to Atlas. It models assignments, expressions, invocations, source locations, taint traces, findings, severities, confidence, CWE and OWASP mappings.

## Initial rules

The engine detects tainted data reaching SQL, command, filesystem, network, deserialization and reflection sinks. It also detects hardcoded secrets, weak cryptography, potentially unsafe XML parsing, disabled CSRF/TLS and unrestricted Spring Boot actuator exposure.

Known sanitizers break taint propagation. Findings include source-to-sink traces and stable fingerprints. Reports export to deterministic JSON and SARIF 2.1.0 for CI and code-scanning integrations.

## Scope

PR38 intentionally defines an analysis IR rather than coupling rules to one parser. Java front ends can translate resolved Java expressions and calls into `SecurityProgram`; later PRs can add framework-aware extraction and interprocedural taint summaries without changing the reporting model.

# PR48 — Cross-Language Intermediate Representation

PR48 introduces a compact, deterministic intermediate representation shared by Java, Kotlin, Scala, and Groovy source files.

## Capabilities

- language detection from source extensions
- package, import, annotation, type, function, parameter, assignment, return, and call extraction
- Java, Kotlin, Scala, and Groovy frontends
- top-level function support
- shared qualified function identifiers
- deterministic workspace symbol indexing
- cross-language call-edge resolution
- conservative fan-out for ambiguous dynamic calls
- unresolved-call reporting
- workspace metrics by language

The frontend is deliberately dependency-free and tolerant. It provides the common structural layer used by later call-graph, taint, symbolic, reporting, and IDE integrations without replacing the mature Java-specific parser.

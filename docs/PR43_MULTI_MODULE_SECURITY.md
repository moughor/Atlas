# PR43 — Multi-module security analysis

PR43 adds deterministic workspace composition for Java repositories containing Maven, Gradle, or plain modules.

## Capabilities

- module descriptors and workspace discovery
- Maven and Gradle dependency extraction
- deterministic module graph construction
- unresolved dependency reporting
- strongly connected component cycle detection
- dependency-first scan ordering
- transitive dependency queries
- changed-module impact propagation
- per-module security reports
- aggregate workspace findings and metrics

The implementation composes the existing Java security frontend rather than duplicating rule logic.

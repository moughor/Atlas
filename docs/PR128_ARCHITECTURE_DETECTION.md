# PR128 — Architecture Detection

Atlas detects repository architecture from the structured PR127 repository
summary and PR125 semantic graph. It does not inspect raw source during this
stage.

The report covers layered architecture, modular monoliths, microservices,
hexagonal architecture, clean architecture, CQRS, event-driven systems, and
plugin architectures. It also records dependency directions and cycles,
bounded contexts, ports, adapters, and infrastructure layers.

Every architecture finding includes:

- a normalized architecture name;
- a bounded confidence score;
- one or more evidence records with kind, stable reference, and detail.

`JavaArchitectureGraph` can optionally enrich dependency directions without
changing its existing API. The report is published as
`semantic_context.architecture`.

## PR127 checkpoint guidance

Applied during PR128:

- consume repository summary and semantic graph instead of raw files;
- use independently replaceable detector strategies;
- retain traceable evidence and confidence;
- build on, rather than replace, `java_architecture`.

Deferred:

- unification of `semantic_graph` and `knowledge_graph` belongs to PR129;
- expression-inference performance is unrelated to architecture detection;
- repository-wide CHANGELOG restructuring is out of scope;
- generic analyzer failure isolation and empty-project summary coverage remain
  useful standalone hardening tasks but were not required by PR128 behavior.

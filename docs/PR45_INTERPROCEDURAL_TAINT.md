# PR45 — Interprocedural Taint Analysis

PR45 adds a deterministic whole-program Java taint engine on top of the existing Atlas security rule catalog.

## Capabilities

- parses Java types, fields, methods, parameters, annotations, and method bodies
- discovers Spring/Jakarta-style request entrypoints and `main`
- supports explicit entrypoint selection
- propagates untrusted values through local assignments and concatenation
- maps tainted arguments into resolved callees
- propagates tainted return values back to callers
- follows multi-hop call chains across files and packages
- recognizes the existing Atlas source, sanitizer, and sink catalogs
- reports source-to-sink traces with call-return steps
- builds deterministic method summaries to a fixpoint
- records call edges, analyzed contexts, unresolved calls, and convergence metrics
- preserves the PR38 intraprocedural engine as a compatible lightweight analysis path

## API

```python
from moughorai.interprocedural_taint import InterproceduralTaintAnalyzer
from moughorai.java_security import JavaSourceUnit

report = InterproceduralTaintAnalyzer().analyze_units((
    JavaSourceUnit("Controller.java", controller_source),
    JavaSourceUnit("Service.java", service_source),
))
```

The returned `InterproceduralTaintReport` contains findings, method summaries, metrics, and deterministic unresolved-call warnings.

## Limits

PR45 intentionally uses a bounded, source-level Java model. Dynamic reflection, runtime dependency injection resolution, aliases through arbitrary heap objects, polymorphic collections, and framework-specific semantic models remain future roadmap items. PR46 will introduce explicit framework models.

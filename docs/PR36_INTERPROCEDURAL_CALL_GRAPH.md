# PR36 — Interprocedural Call Graph

PR36 adds a deterministic, method-level call graph subsystem under
`moughorai.call_graph`. It complements the existing architectural
`java_callflow` package rather than replacing it.

## Capabilities

- Normalized Java type, method, and call-site facts.
- Static and special dispatch resolution.
- Virtual and interface dispatch through a type hierarchy.
- Dynamic, lambda, and method-reference call-site representation.
- External and unresolved target reporting.
- Direct and transitive caller/callee queries.
- Bounded path enumeration and shortest-path lookup.
- Tarjan strongly connected components and recursion detection.
- Roots, leaves, statistics, and deterministic JSON export.

## Minimal example

```python
from moughorai.call_graph import (
    CallGraphService, CallSite, MethodId, MethodSymbol, TypeSymbol,
)

controller = MethodSymbol(MethodId("app.Controller", "handle"))
service = MethodSymbol(MethodId("app.Service", "process"))

report = CallGraphService().build(
    [TypeSymbol("app.Controller"), TypeSymbol("app.Service")],
    [controller, service],
    [CallSite(controller.id, "app.Service", "process")],
)

assert report.graph.callees(controller.id) == (service.id,)
```

## Design constraints

The builder consumes normalized facts. Parsing Java source and producing those
facts is intentionally kept outside this subsystem so existing parsers,
semantic IR, symbol databases, and future bytecode adapters can share the same
call-graph engine.

# PR129 Release Notes

PR129 consolidates Atlas repository, cross-language symbol, dependency,
framework, and build-system metadata through the existing `KnowledgeGraph`.

The published `semantic_graph` contains repository structure, cross-language
symbols, resolved imports, Java/Python inheritance, verified Java overrides,
declared and project dependencies, frameworks, and build systems. Composition,
calls, and concrete build targets remain explicitly unpopulated until reliable
normal-pipeline evidence exists. PR125 JSON fields and the legacy PR27 builder
API remain compatible. Graph JSON can be restored with
`KnowledgeGraph.from_dict()` and queried through the established graph methods.

Serialization is exactly idempotent. Dependency node identity preserves
version and scope. The integration remains source-free and additive, and
specialized language and analysis graphs remain available.

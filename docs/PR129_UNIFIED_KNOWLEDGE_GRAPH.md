# PR129 — Unified Knowledge Graph

Atlas now consolidates its existing repository and semantic facts through the
original `KnowledgeGraph` abstraction. This is an additive Atlas 2.x
integration, not a replacement for language-specific or analysis-specific
graphs.

## Model

The graph contains these node kinds:

- repository, workspace, project, package, and module;
- type, method, and field;
- declared dependency, detected framework, and detected build system.

Production snapshots record resolved imports, Java/Python inheritance,
verified Java overrides, declared dependencies, project dependencies,
membership, and ownership. Composition and calls remain model capabilities but
are not advertised as populated because the normal analyzer pipeline does not
yet provide reliable lifecycle or resolved-call evidence. Every production
edge carries evidence identifying the structured Atlas fact that produced it.
Missing or ambiguous relationships are not guessed.

`build_system` is the production node kind for Gradle, Maven, npm, and similar
detections. The legacy `build_target` enum remains available, but no build
target/task node is emitted until Atlas has task-level evidence.

See [`PR129_RELATION_EVIDENCE.md`](PR129_RELATION_EVIDENCE.md) for the exact
production mapping and limitations.

## Snapshot compatibility

`semantic_context.semantic_graph` remains deterministic JSON. Existing PR125
fields are retained on every node:

- `id`;
- `kind`;
- `qualified_name`;
- `project_id`;
- `language`.

The optional additive `name`, `symbol_id`, and `metadata` fields are emitted
only when they add information beyond the PR125 fields. Edge evidence and the
graph schema allow richer consumers without breaking existing traversal.
Serialization is canonical: serializing, restoring with `from_dict()`, and
serializing again produces exactly equal data.

## Snapshot size

On the validated 41-project JUnit workspace, PR129 increases the complete
snapshot from 13,682,363 to 15,418,187 bytes (+12.69%). The compact semantic
graph grows from 4,044,669 to 4,929,300 bytes (+21.87%), with nodes increasing
1.02% and edges 21.08%. Optional fields equal to existing PR125 values are
omitted to avoid redundant serialization. Graph persistence remains linear in
nodes and edges; future large-workspace work should monitor this measured
overhead rather than assume graph storage is free.

## Query API

```python
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind

graph = KnowledgeGraph.from_dict(snapshot.semantic_context["semantic_graph"])
projects = graph.by_kind(KnowledgeKind.PROJECT)
service = graph.find("demo.Service")
neighbors = graph.neighborhood(service[0].id, depth=2)
```

The established `get`, `incoming`, `outgoing`, and `neighborhood` methods and
the legacy `KnowledgeGraphBuilder.build(symbols, dependencies)` signature are
unchanged.

## Review guidance

Applied:

- evolve Atlas toward a semantic graph through compatible consolidation;
- keep language frontends independent behind the analyzer registry;
- make AI/snapshot facts queryable without raw source;
- preserve stable identities and deterministic persistence.

Deferred because it is outside PR129:

- replacing snapshot files with a graph database;
- distributed graph storage and cross-session knowledge persistence;
- agent orchestration;
- repository-scale storage partitioning beyond the existing snapshot model.
- canonical call and composition edges until reliable producers are connected.

Those concerns remain roadmap work for PR145, PR148, and PR150 rather than
being pulled into PR129.

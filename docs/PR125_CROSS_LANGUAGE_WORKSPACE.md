# PR125 — Cross-Language Workspace

Atlas semantic snapshots now contain a deterministic `semantic_graph` built
from project-scoped global symbols. Java, Python, and TypeScript declarations
share the same node collection. Ownership and resolvable import relationships
are represented as stable edges.

The built-in TypeScript frontend supports `.ts` and `.tsx` declaration
discovery for modules, classes, interfaces, enums, type aliases, and functions.
It records static imports without executing Node.js or project code.

Graph nodes retain symbol IDs, project identity, language, kind, and qualified
name. Existing snapshot fields remain unchanged; the graph is additive.

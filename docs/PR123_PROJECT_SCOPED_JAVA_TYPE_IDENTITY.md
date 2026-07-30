# PR123 — Project-Scoped Java Type Identity

PR123 allows the same Java qualified type name to coexist in independent Atlas
workspace projects.

## Identity

Global symbols now carry an optional `project_id`. Scoped symbol IDs are derived
from `(kind, project_id, qualified_name)`. Legacy symbols without a project keep
their previous IDs and lookup behavior.

The global database indexes `(project_id, qualified_name)` while retaining:

- the legacy first-match `by_qualified_name(name)` lookup;
- a scoped `by_qualified_name(name, project_id)` lookup;
- `find_qualified(name)` for all project-local definitions.

Snapshot JSON includes `project_id` only for scoped symbols, preserving the
shape and identifiers of existing unscoped snapshots.

## Duplicate policy

Two projects may contain the same default-package or fully qualified Java type.
Two definitions with the same qualified name inside one project remain an
error. `DuplicateTypeError` identifies the project and both source paths.

Persistence, recovery, source removal, immutable snapshots, and concurrent
database operations retain the project scope.

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

## Build-managed source roots

For Maven projects, Java analysis reuses the module scanner's recognized Java source
roots. Standard main and test sources remain eligible, while Java-looking fixture
files under Maven resource roots are excluded because Maven copies resources rather
than compiling them. Maven reactor and statically declared Gradle modules are
discovered as independent Atlas projects, so a qualified type may legitimately occur
in two artifacts without weakening duplicate detection inside either artifact.

Gradle version-specific source sets such as `src/main/java21` may deliberately
override a qualified type from `src/main/java`. Atlas does not yet model source-set
variants. When both exact relative paths are eligible, Atlas keeps the baseline and
omits only its version-specific overlay with an explicit warning. Additive files in
version-specific roots and custom roots such as `testFixtures` or JMH retain the
legacy scan for backward compatibility.

For Maven, custom source roots require structured build metadata. Atlas does not
infer a Maven compile root merely because a resource directory contains a nested
`src/main/java` path. Gradle retains the legacy project-bounded Java scan because
Atlas does not evaluate source-set configuration; Java-looking files in custom or
resource roots can therefore be analyzed unless workspace enumeration excludes
them. They remain in one unversioned semantic scope and are not proof that Gradle
compiles those files.

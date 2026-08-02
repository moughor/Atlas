# PR123 — Project-Scoped Java Type Identity

PR123 allows the same Java qualified type name to coexist in independent Atlas
workspace projects.

## Identity

Global symbols carry an optional `project_id` and may also carry an optional
`scope_id`. Project-scoped symbol IDs without a source scope continue to derive
from `(kind, project_id, qualified_name)`. Symbols isolated into a source scope
derive their IDs from `(kind, project_id, scope_id, qualified_name)`. Legacy
symbols without a project and existing project-scoped symbols without a source
scope keep their previous IDs and lookup behavior byte for byte.

When present, `scope_id` must be a non-empty string without surrounding
whitespace. This validation applies to new symbols and persisted symbols loaded
through Atlas stores.

The global database uses `(project_id, scope_id, qualified_name, kind)` for exact
identity and retains a secondary `(project_id, qualified_name)` lookup index. The
public lookup behavior remains compatible:

- the legacy first-match `by_qualified_name(name)` lookup;
- a project-scoped `by_qualified_name(name, project_id)` lookup that returns the
  deterministic first match when several source scopes or kinds exist;
- an additive exact-scope `by_qualified_name(name, project_id,
  scope_id=...)` lookup;
- `find_qualified(name)` for all project-local definitions.

Snapshot JSON includes `project_id` only for project-scoped symbols and includes
`scope_id` only when a source scope exists. Analysis-result persistence and the
global symbol store accept schema-1 payloads without `scope_id` and omit the field
again when saving an unscoped symbol. Existing unscoped and project-only payload
shapes and identifiers therefore remain unchanged.

## Duplicate policy

Two projects may contain the same default-package or fully qualified Java type.
Two definitions with the same qualified name inside one project normally remain
an error. `DuplicateTypeError` identifies the project and both source paths.

For a Gradle project, Atlas can recover conservatively when those two paths prove
that the conflict crosses distinct conventional `src/<sourceSet>/java` roots. The
recovery is used only when every successfully parsed Java input belongs to such a
root and neither conflicting source set is a version root such as `main21` or
`test21`. Atlas then builds each source set independently and gives its packages,
types and members deterministic scope-aware IDs. Owner IDs are remapped into the
same scope, so members cannot attach to a same-named type in another source set.

A duplicate within one source set still raises `DuplicateTypeError`. Loose paths,
non-conventional roots, version-root ambiguity, or any input that cannot be scoped
without guessing also preserve the error instead of weakening duplicate detection.

Persistence, recovery, source removal, immutable snapshots, and concurrent
database operations retain both project and optional source scope.

## Build-managed source roots

For Maven projects, Java analysis reuses the module scanner's recognized Java source
roots. Standard main and test sources remain eligible, while Java-looking fixture
files under Maven resource roots are excluded because Maven copies resources rather
than compiling them. Maven reactor and statically declared Gradle modules are
discovered as independent Atlas projects, so a qualified type may legitimately occur
in two artifacts without weakening duplicate detection inside either artifact.

Gradle version-specific roots may place an alternative in either
`src/main/javaNN` or `src/mainNN/java`, with equivalent `test` layouts. Atlas does
not select a target Java version or model multi-release variants. When an eligible
alternative has the exact same relative tail as an eligible
`src/main/java` or `src/test/java` baseline, Atlas keeps the baseline and omits only
that exact alternative with an explicit warning. Additive files without an exact
baseline counterpart remain eligible. Version roots are never reinterpreted as
independent conventional source scopes merely to make a duplicate disappear.

For Maven, custom source roots require structured build metadata. Atlas does not
infer a Maven compile root merely because a resource directory contains a nested
`src/main/java` path. Other Java projects now separate the complete repository
inventory from compiled semantic inputs through bounded, evidence-ordered source
selection. Atlas recognizes direct literal Gradle `java/resources.srcDir(s)` calls,
root-registered IntelliJ module source/resource roots, established conventional
source sets, and generated roots without executing build logic. Owner-relative
`testData` and `test-data` trees remain inventory-only when no stronger compiled
root evidence exists. Independently discovered projects and explicitly registered
module roots override that fallback.

Assignments, variables, multiline calls, alternative Gradle source-set APIs, and
executable build logic are not evaluated. Unsupported custom-root syntax remains
unknown rather than being inferred from a nested directory named `src`. Source-set
identity is introduced only by the evidence-backed duplicate recovery described
above, not by speculative build configuration inference. See
`stability/INTELLIJ_FIXTURE_SOURCE_ROOT_INVESTIGATION.md` for the evidence hierarchy,
preservation cases, and current JPS module-scoping limitation.

Recovered source sets preserve every successfully parsed symbol plus deterministic
member ownership, visibility, annotations, and Java `main` entry-point metadata.
They also carry explicit partial-analysis and conventional-source-scope evidence.
Atlas does not merge potentially ambiguous architecture information across those
scopes: the recovered Java document omits the Java architecture artifact, marks
architecture relations unavailable, and emits one source-free warning for the
project. The warning contains neither raw source nor an absolute source location.

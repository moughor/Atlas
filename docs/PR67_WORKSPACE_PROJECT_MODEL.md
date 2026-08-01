# PR67 — Workspace & Project Model

PR67 introduces a deterministic multi-project workspace layer for Atlas.

## Capabilities

- Load `atlas.yaml` or `atlas.yml` workspace manifests.
- Define named projects, paths, dependencies, include/exclude globs, and string-normalized options.
- Discover projects from standard ecosystem markers when no manifest exists.
- Validate duplicate names, path traversal, missing dependencies, and dependency cycles.
- Produce deterministic dependency and analysis orderings.
- Compute content fingerprints and identify changed projects.
- Expand changes to transitively impacted downstream projects.
- Serialize workspace state deterministically for API, CLI, and LSP consumers.

## Example

```yaml
projects:
  - name: core
    path: packages/core
    include: ["**/*.py"]
  - name: api
    path: services/api
    dependencies: [core]
    exclude: ["build/**/*"]
options:
  profile: strict
```

```python
from moughorai.workspace import WorkspaceService

service = WorkspaceService(".")
plan = service.analysis_order(("api",))
```

The plan includes all required dependencies in stable topological order.

## Maven reactor discovery

When no `atlas.yaml` is present, Atlas follows explicit Maven `<modules>`
declarations recursively, including modules below the generic directory-scan depth.
Only declared modules whose POM remains inside the workspace are added. Each reactor
module receives its own project identity, and ancestor projects exclude files owned
by their discovered descendants.

This keeps independent Maven artifacts separate without treating arbitrary POMs in
test resources as workspace projects. Invalid or undeclared fixture trees remain
outside reactor discovery.

## Gradle settings discovery

Automatic discovery statically recognizes top-level literal Gradle declarations in
both parenthesized and Groovy command form, including multiple literal arguments and
colon-separated nested project paths:

```groovy
include(":core", ":services:api")
include "framework-docs"
```

Atlas does not execute settings scripts. Variables, interpolation, conditionals,
collections and loops, `projectDir` remapping, `includeBuild`, and nested settings
evaluation remain unsupported. A declared directory must exist, resolve inside the
workspace, and use a conservative project-path grammar. Settings evidence is merged
with a project already found through another marker instead of creating a duplicate.
Ancestor file ownership is then pruned exactly as for Maven reactor modules.
Colon-separated paths also create each existing intermediate Gradle project, matching
Gradle's project hierarchy semantics.

Resolved-path aliases and flattened project names must be unambiguous. If two Gradle
paths resolve to the same physical branch, or two physical paths would receive the
same established Atlas name, Atlas omits the affected declared branch and its
descendants rather than publishing an unstable identity.

Gradle membership proves the build system but does not prove the name or dependency
contents of a custom child build file. Atlas does not classify arbitrary `*.gradle`
scripts as project descriptors. If both settings filenames exist, Atlas treats their
authority as ambiguous and does not combine their declarations.
